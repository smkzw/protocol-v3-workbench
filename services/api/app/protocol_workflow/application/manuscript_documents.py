"""Save one complete working document through the product's existing UoW."""
import hashlib
import re

from packages.contracts.workbench_contracts.protocol_v3 import ActorType, SemanticDocumentRevision
from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.canonical.document import document_revision_hash
from app.protocol_workflow.events.models import verify_event_integrity
from app.protocol_workflow.events.unit_of_work import EventSourcedUnitOfWork
from app.protocol_workflow.agent3.manuscript_document import assemble_working_manuscript
from app.protocol_workflow.qc.manuscript_qc import run_manuscript_qc
from .manuscript_edits import (
    _digit_bounded, _fact_display_text, _negated, _norm_fact_text,
    block_content_text, edit_intent_sha256, reclassify_edit)


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
            accepted_candidate_id = None
            for event in uow.event_stream_repository.read_events(project_id, document_id):
                if event.event_type != 'manuscript_external_candidate_accepted.v1':
                    continue
                verify_event_integrity(event)
                accepted_candidate_id = event.payload.get('candidate_id') or None
        if document is None:
            return None
        return {'document': document.model_dump(mode='json'),
            'document_sha256': document_revision_hash(document),
            'revision': document.revision,
            'accepted_candidate_id': accepted_candidate_id}

    @staticmethod
    def _source_policy_intent(project_id, study_id, intent):
        return hashlib.sha256(canonical_json([
            project_id, study_id, 'source-policy', intent['operation_id'],
            intent['source_manifest_sha256'], sorted(intent['source_ids']),
            list(intent['routine_scope']), list(intent['excluded_scope']),
        ]).encode()).hexdigest()

    def source_policy_status(self, project_id, study_id, source_manifest_sha256):
        """Return the latest project-level SOP/reference applicability record."""
        document_id = manuscript_document_id(project_id, study_id)
        latest = None
        with self.uow_factory() as uow:
            for event in uow.event_stream_repository.read_events(project_id, document_id):
                if event.event_type != 'manuscript_source_policy_confirmed.v1':
                    continue
                verify_event_integrity(event)
                latest = dict(event.payload)
        if latest is None:
            return {'status': 'not_confirmed', 'current': False}
        latest['current'] = latest.get('source_manifest_sha256') == source_manifest_sha256
        latest['status'] = 'confirmed' if latest['current'] else 'source_version_changed'
        return latest

    def confirm_source_policy(self, project_id, study_id, intent):
        """Persist one project-level confirmation; identical source versions reuse it.

        This confirms only routine operating-language reuse.  Dose, safety and
        statistical decisions remain outside this record and keep their own
        decision cards.
        """
        if not intent.get('source_manifest_sha256') or not intent.get('source_ids'):
            raise ValueError('source_policy_sources_missing')
        if not intent.get('routine_scope'):
            raise ValueError('source_policy_scope_missing')
        document_id = manuscript_document_id(project_id, study_id)
        intent_sha = self._source_policy_intent(project_id, study_id, intent)
        with self.uow_factory() as uow:
            latest = None
            for event in uow.event_stream_repository.read_events(project_id, document_id):
                if event.event_type != 'manuscript_source_policy_confirmed.v1':
                    continue
                verify_event_integrity(event)
                payload = dict(event.payload)
                latest = payload
                if payload.get('operation_id') == intent['operation_id']:
                    if payload.get('intent_sha256') != intent_sha:
                        raise ValueError('source_policy_intent_changed')
                    return {**payload, 'replayed': True, 'current': True}
            if (latest is not None
                    and latest.get('source_manifest_sha256') == intent['source_manifest_sha256']
                    and latest.get('source_ids') == sorted(intent['source_ids'])
                    and latest.get('routine_scope') == list(intent['routine_scope'])
                    and latest.get('excluded_scope') == list(intent['excluded_scope'])):
                return {**latest, 'replayed': True, 'current': True,
                        'reused_project_confirmation': True}
            now = self.clock()
            payload = {
                'operation_id': intent['operation_id'],
                'intent_sha256': intent_sha,
                'source_manifest_sha256': intent['source_manifest_sha256'],
                'source_ids': sorted(intent['source_ids']),
                'routine_scope': list(intent['routine_scope']),
                'excluded_scope': list(intent['excluded_scope']),
                'confirmed_by': intent['actor_id'],
                'confirmed_at': now.isoformat(),
                'current': True,
                'acceptance_scope': 'routine_operational_language_only',
            }
            params = {
                'domain_event_id': 'manuscript-source-policy:' + hashlib.sha256(
                    canonical_json([document_id, intent['operation_id']]).encode()
                ).hexdigest(),
                'stream_id': document_id,
                'event_type': 'manuscript_source_policy_confirmed.v1',
                'payload_schema_version': 'mw_protocol_v3_event_v1',
                'upcaster_id': 'noop:v1',
                'actor_type': ActorType.USER,
                'actor_id': intent['actor_id'],
                'action': 'confirm_project_source_policy',
                'reason': '项目级确认常规运营SOP适用范围；关键剂量、安全和统计决定仍分别确认。',
                'payload': payload,
                'emitted_at': now,
            }
            head = uow.event_stream_repository.get_stream_head(project_id, document_id)
            if head is None:
                built = self.atomic.builder.build(
                    sequence=1, previous_event_sha256=None, **params)
            else:
                built = self.atomic.builder.continue_chain(
                    head_sha256=head.last_event_sha256,
                    head_sequence=head.last_sequence, **params)
            uow.event_stream_repository.append_events(project_id, document_id, [built])
            uow.commit()
        return {**payload, 'replayed': False, 'reused_project_confirmation': False}

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

    @staticmethod
    def _candidate_intent(project_id, study_id, intent):
        return hashlib.sha256(canonical_json([
            project_id, study_id, 'external-candidate', intent['operation_id'],
            intent['candidate_id'], intent['candidate_sha256'],
            intent.get('evidence_manifest_sha256'),
            intent['expected_revision'], intent.get('expected_document_sha256'),
        ]).encode()).hexdigest()

    def _candidate_receipt(self, uow, project_id, study_id, intent):
        document_id = manuscript_document_id(project_id, study_id)
        for event in uow.event_stream_repository.read_events(project_id, document_id):
            if event.event_type != 'manuscript_external_candidate_accepted.v1' \
                    or event.payload.get('operation_id') != intent['operation_id']:
                continue
            verify_event_integrity(event)
            if event.payload['intent_sha256'] != self._candidate_intent(
                    project_id, study_id, intent):
                raise ValueError('manuscript_candidate_intent_changed')
            document = SemanticDocumentRevision.model_validate(event.payload['document'])
            if document_revision_hash(document) != event.payload['document_sha256']:
                raise ValueError('manuscript_candidate_document_changed')
            return {
                'document': document.model_dump(mode='json'),
                'document_sha256': event.payload['document_sha256'],
                'operation_id': intent['operation_id'], 'replayed': True,
                'status': 'working_draft',
                'candidate_id': intent['candidate_id'],
                'unresolved_items': list(event.payload.get('unresolved_items') or []),
            }
        return None

    def recover_candidate(self, project_id, study_id, intent):
        with self.uow_factory() as uow:
            return self._candidate_receipt(uow, project_id, study_id, intent)

    def accept_candidate(self, project_id, study_id, intent, document_builder):
        """Atomically activate one immutable candidate as the semantic work draft.

        The builder is pure and receives the current study/document identities.
        Candidate artifacts may be written before this call, but the current
        document pointer advances only with this transaction and event receipt.
        """
        existing = self.recover_candidate(project_id, study_id, intent)
        if existing is not None:
            return existing
        document_id = manuscript_document_id(project_id, study_id)
        with self.uow_factory() as uow:
            existing = self._candidate_receipt(uow, project_id, study_id, intent)
            if existing is not None:
                return existing
            current = uow.semantic_document_repository.get_current(project_id, document_id)
            if ((current.revision if current else 0) != intent['expected_revision']
                    or (document_revision_hash(current) if current else None)
                    != intent.get('expected_document_sha256')):
                raise ValueError('manuscript_document_revision_changed')
            study = uow.study_definition_repository.get_current(project_id, study_id)
            if study is None:
                raise ValueError('manuscript_study_missing')
            now = self.clock()
            document = document_builder(study, current, document_id, now)
            if not isinstance(document, SemanticDocumentRevision):
                raise ValueError('manuscript_candidate_document_invalid')
            payload = {
                'operation_id': intent['operation_id'],
                'intent_sha256': self._candidate_intent(project_id, study_id, intent),
                'candidate_id': intent['candidate_id'],
                'candidate_sha256': intent['candidate_sha256'],
                'evidence_manifest_sha256': intent.get('evidence_manifest_sha256'),
                'document': document.model_dump(mode='json'),
                'document_sha256': document_revision_hash(document),
                'unresolved_items': list(intent.get('unresolved_items') or []),
                'acceptance_scope': 'working_draft_only',
            }
            self.atomic.build_and_apply(
                uow, project_id=project_id, stream_id=document_id,
                aggregate=document,
                cas_repository_handle_name='semantic_document_cas_repository',
                expected_revision=intent['expected_revision'], event={
                    'domain_event_id': 'manuscript-candidate:' + hashlib.sha256(
                        canonical_json([document_id, intent['operation_id']]).encode()
                    ).hexdigest(),
                    'stream_id': document_id,
                    'event_type': 'manuscript_external_candidate_accepted.v1',
                    'payload_schema_version': 'mw_protocol_v3_event_v1',
                    'upcaster_id': 'noop:v1',
                    'actor_type': ActorType.USER,
                    'actor_id': intent['actor_id'],
                    'action': 'accept_external_working_draft_candidate',
                    'reason': '采用有来源的候选正文进入当前工作稿；缺口与待决定项继续保留。',
                    'payload': payload,
                    'emitted_at': now,
                })
            return {
                'document': document.model_dump(mode='json'),
                'document_sha256': payload['document_sha256'],
                'operation_id': intent['operation_id'], 'replayed': False,
                'status': 'working_draft',
                'candidate_id': intent['candidate_id'],
                'unresolved_items': payload['unresolved_items'],
                'qc': run_manuscript_qc(document.model_dump(mode='json')),
            }

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
        """Snapshot-bound reconciliation bound to the *current* study (audit G2/F06).

        The confirmed facts are actually read here: every edit signal is
        compared against the fact value now in ``confirmed_facts`` — a study
        value that changed after the draft was written (100例 → 1000例) is a
        difference, not a pass.  Status vocabulary is honest about coverage:

        - ``differences``: at least one unresolved deviation (missing text or
          a fact that drifted from the confirmed value).
        - ``consistent_within_checked_scope``: every checked deviation was
          re-verified against the current text AND current facts; this never
          claims the whole document is consistent.
        - ``not_checked``: no machine-checkable signals exist for this
          revision; nothing was verified and nothing is being blessed.

        ``checked_block_count``/``content_block_count`` expose the coverage so
        a UI can never render "not checked" as "verified consistent".
        Resolutions only close differences for the study version they were
        acknowledged on (F06/RC-08).
        """
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
        # A resolution closes a difference only on the study version it was
        # acknowledged against; legacy resolutions recorded before the study
        # binding existed stay accepted but are counted honestly.
        resolutions, legacy_resolutions = set(), 0
        for event in events:
            if event.event_type != 'manuscript_reconciliation_resolved.v1':
                continue
            bound_study = event.payload.get('study_revision_sha256')
            if bound_study is None:
                legacy_resolutions += 1
                resolutions.add((event.payload.get('semantic_block_id'),
                                 event.payload.get('document_revision')))
            elif bound_study == study_revision_sha256:
                resolutions.add((event.payload.get('semantic_block_id'),
                                 event.payload.get('document_revision')))
        content_block_count = sum(
            1 for block in document.semantic_blocks if block_content_text(
                block.model_dump(mode='json')).strip())
        items, differences = [], 0
        for block_id in sorted(clues):
            clue = clues[block_id]
            signals = clue.get('signals') or ()
            block = blocks.get(block_id)
            if block is None:
                continue
            text = block_content_text(block.model_dump(mode='json'))
            # 绑定路径 = 编辑线索路径 ∪ 块自身声明的 fact 绑定（后者是
            # 权威：即使本次编辑未触碰事实，研究事实更新后块仍需重核）。
            paths = tuple(dict.fromkeys(
                list(clue.get('affected_fact_paths') or [])
                + list(getattr(block, 'fact_paths', ()) or ())))
            missing = []
            stale_fact_paths = []
            deep_fact_paths = []
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
                # F06/RC-07: the fact itself moved on after this text was
                # written — the confirmed value no longer matches the value
                # this block was written against.
                current_value = confirmed_facts.get(signal.get('fact_path')) if confirmed_facts else None
                current_text = _fact_display_text(current_value)
                if current_text and signal.get('present_in_old') \
                        and not _digit_bounded(_fact_display_text(current_value), value) \
                        and _norm_fact_text(current_text) != _norm_fact_text(value):
                    if signal.get('fact_path') not in stale_fact_paths and \
                            signal.get('fact_path') not in missing:
                        stale_fact_paths.append(signal['fact_path'])
            for path in paths:
                # F06/RC-07 fact drift: compare the block text against the
                # fact value *now* in the confirmed set. Scalar facts only:
                # a structured regimen projection cannot be checked by text
                # matching, so it is declared as deep-unverified instead of
                # guessed at (honest coverage beats false assurance). The
                # comparison only fires when the block carries numbers from
                # the fact's topic, so prose bound to a fact without
                # restating its values is not a contradiction.
                if not isinstance(confirmed_facts, dict):
                    continue
                current_value = confirmed_facts.get(path)
                if isinstance(current_value, (dict, list)):
                    if path not in deep_fact_paths:
                        deep_fact_paths.append(path)
                    continue
                current_text = _fact_display_text(current_value)
                if not current_text:
                    continue
                fact_digits = re.findall(r'\d+(?:\.\d+)?', current_text)
                text_digits = re.findall(r'\d+(?:\.\d+)?', text)
                if fact_digits and text_digits:
                    if not set(fact_digits) & set(text_digits):
                        continue  # 块不承载该事实的数值话题
                    drifted = any(not _digit_bounded(text, digit) for digit in fact_digits)
                elif not fact_digits:
                    drifted = bool(_norm_fact_text(current_text)) and \
                        _norm_fact_text(current_text) not in _norm_fact_text(text)
                else:
                    continue  # 事实有数字而块全文无数字：不适用数字 drift
                if drifted and path not in stale_fact_paths and path not in missing:
                    stale_fact_paths.append(path)
            status = ('difference' if (missing or stale_fact_paths) else 'consistent')
            resolved = (block_id, document.revision) in resolutions
            if status == 'difference' and not resolved:
                differences += 1
            items.append({'semantic_block_id': block_id,
                'edit_class': clue.get('edit_class'),
                'affected_fact_paths': list(paths),
                'missing_fact_paths': missing,
                'stale_fact_paths': stale_fact_paths,
                'deep_fact_paths': deep_fact_paths,
                'status': status, 'resolved': resolved})
        checked_block_count = len(items)
        if differences:
            status = 'differences'
        elif checked_block_count:
            status = 'consistent_within_checked_scope'
        else:
            status = 'not_checked'
        return {'schema_version': 'manuscript-reconciliation.v2',
            'document_revision': document.revision,
            'document_sha256': document_revision_hash(document),
            'checked_study_revision_sha256': study_revision_sha256,
            'study_revision_sha256': study_revision_sha256,
            'study_matches_current': True,
            'checked_block_count': checked_block_count,
            'content_block_count': content_block_count,
            'legacy_resolution_count': legacy_resolutions,
            'items': items, 'differences': differences,
            'coverage_note': ('机器核对仅覆盖有编辑线索的章节；'
                f'已核对 {checked_block_count}/{content_block_count} 个内容块，'
                '其余内容未经机器核对，不因本次结果被视为一致。'),
            'status': status}

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
                # F06/RC-08: the acknowledgement binds to the study version it
                # was given on; a later study change reopens the difference.
                'study_revision_sha256': intent.get('study_revision_sha256'),
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
        """Operation identity for one AI object revision (audit G3/F08).

        ``expected_content_sha256`` is deliberately excluded: the client may
        omit it at prepare time while the async apply fills in the real
        anchor hash — a mismatch would make the recovery lookup disagree
        with the original request and invite blind model re-calls.  Anchor
        staleness is a CAS check at apply time, not part of the identity.
        """
        return hashlib.sha256(canonical_json([project_id, study_id, 'object-revision',
            intent['operation_id'], intent['semantic_block_id'],
            intent.get('scope'), intent.get('instruction')]).encode()).hexdigest()

    def _patch_target(self, intent):
        """Validate and return the sub-range locator for patch_object (F07)."""
        target = intent.get('target') or {}
        if not isinstance(target, dict):
            raise ValueError('manuscript_object_scope_invalid')
        kind = target.get('kind')
        if kind == 'table_cell':
            row, column = target.get('row'), target.get('column')
            if not isinstance(row, int) or not isinstance(column, int) \
                    or isinstance(row, bool) or isinstance(column, bool) \
                    or row < 0 or column < 0:
                raise ValueError('manuscript_object_target_invalid')
            return {'kind': 'table_cell', 'row': row, 'column': column}
        if kind == 'text_range':
            start, end = target.get('start'), target.get('end')
            if not isinstance(start, int) or not isinstance(end, int) \
                    or isinstance(start, bool) or isinstance(end, bool) \
                    or start < 0 or end <= start:
                raise ValueError('manuscript_object_target_invalid')
            return {'kind': 'text_range', 'start': start, 'end': end}
        raise ValueError('manuscript_object_target_invalid')

    def prepare_object_revision(self, project_id, study_id, intent):
        """Freeze the anchor and material for one AI object revision.

        The frozen (normalized) intent is persisted as a ``prepared`` event so
        the async apply, a lost receipt, or a worker failure all resolve
        against one durable operation state instead of 404-then-blind-retry
        (audit G3/F08)."""
        if intent.get('scope') not in self.OBJECT_REVISION_SCOPES:
            raise ValueError('manuscript_object_scope_invalid')
        if not str(intent.get('instruction') or '').strip():
            raise ValueError('manuscript_object_instruction_missing')
        if intent.get('scope') == 'patch_object':
            intent = {**intent, 'target': self._patch_target(intent)}
        document_id = manuscript_document_id(project_id, study_id)
        intent_sha256 = self._object_revision_intent(project_id, study_id, intent)
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
            if intent.get('scope') == 'patch_object' \
                    and block.block_kind.value == 'paragraph' \
                    and (intent.get('target') or {}).get('kind') == 'table_cell':
                raise ValueError('manuscript_object_target_invalid')
            if intent.get('scope') == 'patch_object' \
                    and block.block_kind.value == 'table' \
                    and (intent.get('target') or {}).get('kind') == 'text_range':
                raise ValueError('manuscript_object_target_invalid')
            content_sha = hashlib.sha256((block.content or '').encode()).hexdigest()
            expected = intent.get('expected_content_sha256')
            if expected and expected != content_sha:
                raise ValueError('manuscript_object_anchor_changed')
            frozen = {**intent, 'expected_content_sha256': content_sha}
            material = {'schema_version': 'object-revision-request.v1',
                'intent_sha256': intent_sha256,
                'scope': intent['scope'],
                'instruction': intent['instruction'],
                'target': frozen.get('target'),
                'semantic_block_id': intent['semantic_block_id'],
                'block_kind': block.block_kind.value,
                'current_content': block.content,
                'current_content_sha256': content_sha,
                'document_revision': current.revision,
                'document_sha256': document_revision_hash(current)}
            params = {
                'domain_event_id': 'manuscript-object-prepared:' + hashlib.sha256(
                    canonical_json([document_id, intent['operation_id']]).encode()).hexdigest(),
                'stream_id': document_id,
                'event_type': 'manuscript_object_revision_prepared.v1',
                'payload_schema_version': 'mw_protocol_v3_event_v1', 'upcaster_id': 'noop:v1',
                'actor_type': ActorType.USER, 'actor_id': intent['actor_id'],
                'action': 'prepare_object_revision',
                'reason': '冻结一次AI对象修订的完整意图与锚点，供应用/恢复/状态查询共用。',
                'payload': {'operation_id': intent['operation_id'],
                    'intent_sha256': intent_sha256, 'intent': frozen,
                    'status': 'prepared'},
                'emitted_at': self.clock()}
            head = uow.event_stream_repository.get_stream_head(project_id, document_id)
            if head is None:
                built = self.atomic.builder.build(sequence=1, previous_event_sha256=None, **params)
            else:
                built = self.atomic.builder.continue_chain(
                    head_sha256=head.last_event_sha256,
                    head_sequence=head.last_sequence, **params)
            uow.event_stream_repository.append_events(project_id, document_id, [built])
            uow.commit()
        return material

    def object_revision_status(self, project_id, study_id, block_id, operation_id):
        """Operation-level state for one AI revision (audit G3/F08)."""
        document_id = manuscript_document_id(project_id, study_id)
        with self.uow_factory() as uow:
            events = uow.event_stream_repository.read_events(project_id, document_id)
        prepared, revised = None, None
        for event in events:
            if event.payload.get('operation_id') != operation_id:
                continue
            if event.event_type == 'manuscript_object_revision_prepared.v1':
                prepared = event.payload
            elif event.event_type == 'manuscript_object_revised.v1':
                revised = event.payload
        if revised is not None:
            return {'operation_id': operation_id, 'status': 'completed',
                'document_revision': revised.get('document', {}).get('revision')}
        if prepared is not None:
            return {'operation_id': operation_id, 'status': 'running_or_unknown',
                'next_step': '先用原operation_id调用recover核对结果；未知结果不得重新派发模型。'}
        return {'operation_id': operation_id, 'status': 'unknown',
            'next_step': '系统没有该操作的记录，可以重新发起修改。'}

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
            if intent.get('scope') == 'patch_object':
                # F07: a patch touches exactly the authorized sub-range. The
                # candidate replaces only the targeted cell / character range;
                # everything outside must remain identical afterwards.
                target = self._patch_target(intent)
                if target['kind'] == 'table_cell':
                    import json as _json
                    try:
                        parsed = _json.loads(block.content or '{}')
                    except ValueError as exc:
                        raise ValueError('manuscript_object_table_content_invalid') from exc
                    # 块内容与候选契约同形：{"table": {...rows/columns...}}。
                    table = parsed.get('table') if isinstance(parsed, dict) else parsed
                    rows = table.get('rows') if isinstance(table, dict) else None
                    if not isinstance(rows, list) or len(rows) <= target['row']:
                        raise ValueError('manuscript_object_target_invalid')
                    row = rows[target['row']]
                    cells = row.get('cells') if isinstance(row, dict) else None
                    if not isinstance(cells, list) or len(cells) <= target['column']:
                        raise ValueError('manuscript_object_target_invalid')

                    def _mask(rows_value):
                        """Neutralize every cell: whatever survives masking is
                        'outside the authorized range' and must compare equal
                        before/after the patch."""
                        clone = _json.loads(_json.dumps(rows_value))
                        for row_clone in clone:
                            for index, cell in enumerate(row_clone.get('cells', [])):
                                if isinstance(cell, dict):
                                    cell['text'] = ''
                                else:
                                    row_clone['cells'][index] = ''
                        return _json.dumps(clone, ensure_ascii=False, sort_keys=True)

                    new_rows = _json.loads(_json.dumps(rows))
                    cell = new_rows[target['row']]['cells'][target['column']]
                    if isinstance(cell, dict):
                        cell['text'] = candidate
                    else:
                        new_rows[target['row']]['cells'][target['column']] = candidate
                    if _mask(new_rows) != _mask(rows):
                        raise ValueError('manuscript_object_candidate_invalid')
                    candidate = _json.dumps({'table': {**table, 'rows': new_rows}},
                        ensure_ascii=False, sort_keys=True)
                else:  # text_range on a paragraph
                    start, end = target['start'], target['end']
                    text = block.content or ''
                    if end > len(text):
                        raise ValueError('manuscript_object_target_invalid')
                    candidate = text[:start] + candidate + text[end:]
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

    def _office_snapshot_intent(self, project_id, study_id, intent, *, contract='office-snapshot-intent.v2'):
        import base64 as _base64
        content_sha = hashlib.sha256(_base64.b64decode(intent.get('content_base64') or b'')).hexdigest()
        if contract == 'office-snapshot-intent.v1':
            value = [project_id, study_id, 'office-snapshot', intent['operation_id'],
                intent['expected_revision'], content_sha]
        else:
            value = {'contract': 'office-snapshot-intent.v2', 'project_id': project_id,
                'study_definition_id': study_id, 'operation_id': intent['operation_id'],
                'actor_id': intent['actor_id'], 'expected_revision': intent['expected_revision'],
                'expected_document_sha256': intent['expected_document_sha256'],
                'content_sha256': content_sha,
                'base_artifact_revision': intent.get('base_artifact_revision'),
                'opened_study_revision_sha256': intent.get('opened_study_revision_sha256')}
        return hashlib.sha256(canonical_json(value).encode()).hexdigest()

    def _office_snapshot_intent_matches(self, project_id, study_id, intent, payload):
        contract = payload.get('intent_contract') or 'office-snapshot-intent.v1'
        return payload.get('intent_sha256') == self._office_snapshot_intent(
            project_id, study_id, intent, contract=contract)

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
        base_artifact_revision = intent.get('base_artifact_revision')
        with self.uow_factory() as uow:
            # Resolve the head under the same write transaction as the save.
            # 0 means the editor opened before any Office snapshot existed.
            latest = None
            for event in uow.event_stream_repository.read_events(project_id, document_id):
                if event.event_type != 'manuscript_office_snapshot.v1':
                    continue
                verify_event_integrity(event)
                latest = event.payload
                if latest.get('operation_id') == intent['operation_id']:
                    if not self._office_snapshot_intent_matches(project_id, study_id, intent, latest):
                        raise ValueError('manuscript_office_snapshot_intent_changed')
                    return {**latest, 'persisted': True, 'replayed': True}
            if latest is not None and base_artifact_revision is not None \
                    and latest.get('artifact_revision') != base_artifact_revision:
                raise OfficeWorkingCopyConflictError(latest)
            current = uow.semantic_document_repository.get_current(project_id, document_id)
            if current is None:
                raise ValueError('manuscript_document_missing')
            current_hash = document_revision_hash(current)
            expected_matches_current = (current.revision == intent['expected_revision']
                and current_hash == intent['expected_document_sha256'])
            expected_matches_open_word = (latest is not None
                and latest.get('artifact_revision') == base_artifact_revision
                and latest.get('document_revision') == intent['expected_revision']
                and latest.get('document_sha256') == intent['expected_document_sha256'])
            # A newer semantic candidate may coexist with the current Word.
            # Saving that already-open Word keeps its own semantic provenance;
            # choosing the candidate uses the current semantic provenance.
            if not expected_matches_current and not expected_matches_open_word:
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
                'intent_contract': 'office-snapshot-intent.v2',
                'intent_sha256': self._office_snapshot_intent(project_id, study_id, intent),
                'snapshot_id': 'office-snapshot:' + meta.content_sha256,
                'content_sha256': meta.content_sha256,
                'artifact_revision': meta.revision,
                'base_artifact_revision': base_artifact_revision,
                'size_bytes': meta.size_bytes,
                'document_revision': intent['expected_revision'],
                'document_sha256': intent['expected_document_sha256'],
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
                if not self._office_snapshot_intent_matches(
                        project_id, study_id, intent, event.payload):
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

    def office_snapshot_history(self, project_id, study_id):
        """Read saved Word versions without adopting or rebuilding any bytes."""
        document_id = manuscript_document_id(project_id, study_id)
        versions = []
        with self.uow_factory() as uow:
            for event in uow.event_stream_repository.read_events(project_id, document_id):
                if event.event_type != 'manuscript_office_snapshot.v1':
                    continue
                verify_event_integrity(event)
                payload = event.payload
                versions.append({key: payload.get(key) for key in (
                    'operation_id', 'artifact_revision', 'document_revision',
                    'content_sha256', 'size_bytes')})
                versions[-1]['saved_at'] = event.emitted_at.isoformat()
        return list(reversed(versions))

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

    def office_snapshot_reconciliation(self, project_id, study_id, confirmed_facts,
                                       study_revision_sha256):
        """Inspect the actual latest Word bytes; saving never depends on this."""
        latest = self.latest_office_snapshot(project_id, study_id)
        if latest is None:
            return None
        artifact = self.office_snapshot_content(
            project_id, study_id, latest['operation_id'])
        if artifact is None:
            return None
        from .office_projection import project_office_snapshot
        result = project_office_snapshot(
            artifact.content, confirmed_facts,
            snapshot_sha256=latest['content_sha256'],
            study_revision_sha256=study_revision_sha256)
        result['operation_id'] = latest['operation_id']
        result['artifact_revision'] = latest['artifact_revision']
        result['opened_study_revision_sha256'] = latest.get('study_revision_sha256')
        result['study_matches_opened_baseline'] = (
            latest.get('study_revision_sha256') == study_revision_sha256)
        return result


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
