"""One recoverable request for all applicable chapters of the current study."""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from packages.contracts.workbench_contracts.protocol_v3 import (
    AwareDateTime, NonEmptyText, StableId, Sha256)

from app.protocol_workflow.application.queries import GetStudyDefinitionQuery
from app.protocol_workflow.agent3.manuscript_request import prepare_manuscript_request, ManuscriptInputsIncomplete
from app.protocol_workflow.agent3.source_preparation import SourcePreparationIncomplete
from app.protocol_workflow.application.manuscript_documents import OfficeWorkingCopyConflictError
from app.protocol_workflow.graph import GraphRunError
from .chapter_drafts import ChapterPreparationRequest, ChapterStartRequest
from .router import _safe_call


class ChapterFactsResidualConfirmRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_id: StableId
    actor_id: StableId
    expected_revision: int = Field(ge=1, strict=True)
    snapshot_sha256: Sha256
    decided_at: AwareDateTime
    accepted_fact_paths: list[NonEmptyText] = Field(min_length=1)


class ChapterFactsDerivedConfirmRequest(ChapterFactsResidualConfirmRequest):
    candidate_id: StableId


class ManuscriptSaveRequest(ChapterStartRequest):
    operation_id: StableId
    actor_id: StableId
    expected_revision: int = Field(ge=0, strict=True)
    expected_document_sha256: Sha256 | None


def create_manuscript_draft_router(manuscripts, preparations, *, application_service,
        template_loader, documents, route_class, chapter_facts_deriver=None,
        chapter_facts_deriver_factory=None, object_revision_worker_factory=None):
    router = APIRouter(prefix='/api/projects/{project_id}/protocol-workflow/study-definitions/{study_definition_id}/manuscript-draft',
        tags=['研究方案写作'], route_class=route_class)

    def deriver_for(project_id: str, study_definition_id: str):
        """One deriver per study (B09): progress, locks and restart scope are
        study-scoped; a shared instance would cross-talk between studies."""
        if chapter_facts_deriver_factory is not None:
            return chapter_facts_deriver_factory(project_id, study_definition_id)
        return chapter_facts_deriver

    def checked(fn):
        try:
            return fn()
        except ManuscriptInputsIncomplete as exc:
            readiness = exc.readiness
            if not readiness['critical_design_confirmed']:
                message = '关键研究设计尚未确认，确认后即可生成完整工作初稿。'
            else:
                message = '存在与已确认设计矛盾的章节，处理后即可生成；缺口与未决章节不会阻止其余内容。'
            raise HTTPException(409, detail={'message': message,
                'next_step': '请先处理研究建议中未决或冲突的内容，已完成的确认会保留。',
                'readiness': readiness}) from exc
        except SourcePreparationIncomplete as exc:
            raise HTTPException(409, detail={'message': '原写作资料尚未准备完成，请查看资料整理进度。'}) from exc
        except GraphRunError as exc:
            if exc.code in {'graph_run_unknown', 'graph_plan_binding_mismatch'}:
                raise HTTPException(404, detail={'message': '没有找到原写作记录，已有内容已保留。'}) from exc
            raise
        except HTTPException:
            raise
        except ValueError as exc:
            if str(exc) == 'manuscript_study_missing':
                raise HTTPException(404, detail={'message': '没有找到本次研究。'}) from exc
            if str(exc) == 'manuscript_document_revision_changed':
                raise HTTPException(409, detail={'code': 'manuscript_document_revision_changed',
                    'message': '已有更新的文档版本，本次初稿没有覆盖它。',
                    'next_step': '先读取当前文档；需要另存初稿时明确选择保存新版本。'}) from exc
            if str(exc) == 'manuscript_saved_document_changed':
                # A recorded save no longer matches its own event payload:
                # this is an internal invariant breach, not a user mistake.
                raise HTTPException(500, detail={'code': 'internal_invariant_violation',
                    'message': '保存记录的内部核对未通过，系统需要维护。您的已保存内容与操作记录均未改动。',
                    'next_step': '请保留当前页面并稍后再核对；此问题需要工程处理，不需要重新确认研究内容。'}) from exc
            if str(exc) in {'manuscript_request_changed', 'chapter_source_input_changed',
                            'chapter_source_project_mismatch', 'manuscript_document_study_changed',
                            'manuscript_save_intent_changed'}:
                raise HTTPException(409, detail={'message': '研究内容或所选资料已变化，原初稿记录仍然保留。',
                    'next_step': '请先核对当前研究建议，再开始新的整稿写作。'}) from exc
            if str(exc) == 'manuscript_office_content_invalid':
                raise HTTPException(422, detail={'message': '提交的内容不是有效的Word文档，未做任何保存。'}) from exc
            if str(exc) == 'manuscript_office_store_missing':
                raise HTTPException(501, detail={'message': '本部署未启用Office工作副本存储。'}) from exc
            if str(exc) == 'manuscript_object_anchor_changed':
                raise HTTPException(409, detail={'code': 'manuscript_object_anchor_changed',
                    'message': '这段内容在AI准备候选期间又被您编辑过，本次候选没有覆盖您的最新修改。',
                    'next_step': '请基于当前内容重新发起本次AI修改，或先撤销您刚才的编辑再应用候选。'}) from exc
            if str(exc) in {'manuscript_object_scope_invalid', 'manuscript_object_instruction_missing',
                            'manuscript_object_candidate_invalid', 'manuscript_object_kind_unsupported',
                            'manuscript_object_table_content_invalid', 'manuscript_object_intent_changed'}:
                raise HTTPException(422, detail={'message': '本次AI对象修改的请求不完整或目标不支持，原稿未被改动。',
                    'next_step': '请重新描述修改要求；表格内容须保持完整表格结构。'}) from exc
            if str(exc) == 'manuscript_document_incomplete':
                raise HTTPException(409, detail={'message': '完整初稿尚未生成，本次没有保存部分章节覆盖原稿。'}) from exc
            raise
        except Exception as exc:
            # Unclassified failures must not leak traces to the user, and must
            # not invite repeating a medical confirmation that already saved.
            # The operator-side stderr note keeps the failure diagnosable
            # without exposing anything to the UI.
            import sys as _s
            print('MANUSCRIPT UNCLASSIFIED FAIL:', type(exc).__name__, str(exc)[:400],
                  file=_s.stderr)
            raise HTTPException(500, detail={'code': 'internal_unclassified_error',
                'message': '本次操作遇到系统内部问题，已经保存的研究内容、初稿和操作记录全部保留。',
                'next_step': '请稍后重新核对此页状态；如重复出现，请保留页面并反馈，不需要重新确认研究建议。'}) from exc

    def fresh(project, study, body):
        current = application_service.get_study_definition(GetStudyDefinitionQuery(project, study))
        if current.definition is None:
            raise ValueError('manuscript_study_missing')
        if current.revision_sha256 != body.study_revision_sha256:
            raise ValueError('manuscript_request_changed')
        return prepare_manuscript_request(template_loader(), current.definition,
            source_preparation=preparations(project), source_run_id=body.source_run_id)

    def original(owner, study, body):
        try:
            prepared = owner.prepared_request(body.expected_workflow_run_id)
        except GraphRunError as exc:
            if exc.code == 'graph_run_unknown':
                return None
            raise
        payload = prepared.to_payload()
        if (payload['plan']['study_definition_id'] != study
                or payload['plan']['study_sha256'] != body.study_revision_sha256
                or payload['source_run_id'] != body.source_run_id):
            raise ValueError('manuscript_request_changed')
        return owner.read(body.expected_workflow_run_id)

    @router.get('/draft-readiness')
    def draft_readiness_view(project_id: str, study_definition_id: str):
        """Versioned working-draft readiness: critical admission + gap map (R2)."""
        current = application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id, study_definition_id))
        if current.definition is None:
            raise HTTPException(404, detail={'message': '没有找到本次研究。'})
        from app.protocol_workflow.agent3.draft_readiness import draft_readiness
        return draft_readiness(template_loader(), current.definition)

    @router.post('/prepare')
    def prepare(project_id: str, study_definition_id: str, body: ChapterPreparationRequest):
        def execute():
            prepared = fresh(project_id, study_definition_id, body)
            return {'expected_workflow_run_id': manuscripts(project_id).run_id(prepared),
                'input_sha256': prepared.input_sha256, 'plan': prepared.to_payload()['plan']}
        return _safe_call(lambda: checked(execute))

    @router.post('/chapter-facts/derive', status_code=202)
    def derive_chapter_facts(project_id: str, study_definition_id: str, tasks: BackgroundTasks):
        """Prepare chapter-fact recommendations without changing study facts."""
        deriver = deriver_for(project_id, study_definition_id)
        if deriver is None:
            raise HTTPException(501, detail={'message': '本部署未启用章节事实派生。'})
        current = application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id, study_definition_id))
        if current.definition is None:
            raise HTTPException(404, detail={'message': '没有找到本次研究。'})
        from app.protocol_workflow.agent3.chapter_facts import collect_chapter_gaps
        gaps = collect_chapter_gaps(template_loader(), current.definition)
        if not gaps:
            return {'status': 'nothing_to_derive', 'gaps': 0}
        if deriver.progress.get('running'):
            return {'status': 'running', 'gaps': len(gaps),
                    **{k: deriver.progress[k]
                       for k in ('batches_done', 'batches_total')}}
        snapshot = current.revision_sha256
        revision = current.revision
        template = template_loader()
        study = current.definition
        operation_id = 'chapter-facts:' + snapshot
        def run():
            deriver.run(template, study,
                operation_id=operation_id, expected_revision=revision,
                snapshot_sha256=snapshot)
        tasks.add_task(run)
        return {'status': 'started', 'gaps': len(gaps),
                'batches_total': deriver.progress['batches_total']}

    @router.get('/saved')
    def saved_document(project_id: str, study_definition_id: str):
        saved = documents.saved(project_id, study_definition_id)
        if saved is None:
            raise HTTPException(404, detail={'message': '尚未保存完整工作初稿。'})
        return saved

    @router.get('/export/docx')
    def export_docx(project_id: str, study_definition_id: str):
        """Return the current Word bytes; initialize from semantics only once."""
        from fastapi.responses import Response
        latest = documents.latest_office_snapshot(project_id, study_definition_id)
        if latest is not None:
            artifact = documents.office_snapshot_content(
                project_id, study_definition_id, latest['operation_id'])
            if artifact is None:
                raise HTTPException(500, detail={'message': '当前 Word 版本记录存在，但文件暂不可读取。'})
            return Response(content=artifact.content,
                media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                headers={'Content-Disposition': 'attachment; filename="protocol-working-copy.docx"',
                    'X-Content-Sha256': latest['content_sha256'],
                    'X-Export-Scope': 'current_office_snapshot'})
        return _render_semantic_candidate(project_id, study_definition_id)

    @router.get('/candidate/docx')
    def candidate_docx(project_id: str, study_definition_id: str):
        """Render the current semantic candidate without replacing saved Word bytes."""
        return _render_semantic_candidate(project_id, study_definition_id)

    def _render_semantic_candidate(project_id: str, study_definition_id: str):
        from fastapi.responses import FileResponse
        from app.protocol_workflow.agent3.word_export_production import render_production_docx
        from app.protocol_workflow.registries.template_runtime import default_template_root
        import json as _json
        import tempfile as _tempfile
        from pathlib import Path as _Path
        saved = documents.saved(project_id, study_definition_id)
        if saved is None:
            raise HTTPException(404, detail={'message': '尚未保存完整工作初稿，先完成保存再导出。'})
        template_dir = default_template_root()
        template_meta = _json.loads((template_dir / 'template.json').read_text(encoding='utf-8'))
        template_path = template_meta['source']['path']
        # F16: the temp artifact is project-scoped and content-addressed, so
        # two projects sharing a study id/revision can never overwrite each
        # other's export while it is being downloaded.
        import hashlib as _hashlib
        project_scope = _hashlib.sha256(project_id.encode('utf-8')).hexdigest()[:16]
        artifact_scope = _hashlib.sha256(':'.join([
            project_id, study_definition_id, str(saved['revision']),
            saved['document_sha256'] or '']).encode('utf-8')).hexdigest()[:24]
        out_dir = _Path(_tempfile.gettempdir()) / 'mw_protocol_v3_exports' / project_scope
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f'manuscript-{artifact_scope}.docx'
        current = application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id, study_definition_id))
        result = render_production_docx(template_path, template_dir, saved['document'],
            output_path, current.definition.facts if current.definition else {})
        return FileResponse(output_path, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            filename=output_path.name, headers={'X-Document-Sha256': result['document_sha256'],
                'X-Output-Sha256': result['output_sha256'],
                'X-Export-Scope': 'semantic_candidate_docx'})

    @router.get('/chapter-facts/derive')
    def chapter_facts_status(project_id: str, study_definition_id: str):
        deriver = deriver_for(project_id, study_definition_id)
        return {'progress': dict(deriver.progress) if deriver else None}

    @router.post('/chapter-facts/derive/confirm')
    def confirm_derived_chapter_facts(project_id: str, study_definition_id: str,
                                      body: ChapterFactsDerivedConfirmRequest):
        """Write only the current candidate paths explicitly confirmed by the user."""
        import hashlib as _hashlib
        from app.protocol_workflow.application.commands import ApplyStudyDecisionCommand
        from app.protocol_workflow.canonical.decision_inputs import ConfirmationDependency
        from app.protocol_workflow.canonical.hashing import canonical_json
        from packages.contracts.workbench_contracts.protocol_v3 import ActorType, DecisionRecord
        deriver = deriver_for(project_id, study_definition_id)
        candidate = (deriver.progress.get('candidate') if deriver else None)
        if not candidate or candidate.get('candidate_id') != body.candidate_id:
            raise HTTPException(409, detail={'message': '这组章节建议已失效或尚未生成。',
                'next_step': '请重新生成建议并核对后确认。'})
        current = application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id, study_definition_id))
        if current.definition is None:
            raise HTTPException(404, detail={'message': '没有找到本次研究。'})
        if (candidate.get('study_definition_id') != study_definition_id
                or candidate.get('expected_revision') != body.expected_revision
                or candidate.get('snapshot_sha256') != body.snapshot_sha256
                or current.revision != body.expected_revision
                or current.revision_sha256 != body.snapshot_sha256):
            raise HTTPException(409, detail={'message': '研究内容刚有更新，本次建议未采用。',
                'next_step': '请按最新研究内容重新生成章节建议。'})
        available = candidate.get('updates') or {}
        accepted = set(body.accepted_fact_paths)
        updates = {path: value for path, value in available.items() if path in accepted}
        if not updates:
            raise HTTPException(422, detail={'message': '没有选中可确认的章节建议。'})
        selected = body.candidate_id
        record = DecisionRecord(
            decision_record_id='chapter.facts.derivation-record:' + _hashlib.sha256(
                canonical_json([study_definition_id, body.operation_id]).encode()).hexdigest(),
            decision_key='chapter.facts.derivation',
            snapshot_sha256=body.snapshot_sha256,
            expected_state_revision=body.expected_revision,
            state_revision=body.expected_revision + 1,
            option_ids=(selected,), selected_option_id=selected,
            actor_type=ActorType.USER, actor_id=body.actor_id,
            reason='确认按当前研究设计生成的章节事实建议',
            decided_at=body.decided_at)
        dependencies = tuple(ConfirmationDependency(
            fact_path=path,
            rationale='章节事实由该已确认设计事实派生；设计变化后需重新核对') for path in (
            'research.input_context', 'picos.population_summary',
            'picos.primary_endpoint', 'estimand.primary.variable',
            'estimand.primary.ice_strategy',
            'framing.structured_design.comparator_type',
            'framing.structured_design.allocation_ratio') if path in current.definition.facts)
        receipt = application_service.apply_decision(ApplyStudyDecisionCommand(
            project_id=project_id, study_definition_id=study_definition_id,
            idempotency_key=body.operation_id, expected_revision=body.expected_revision,
            actor_type=ActorType.USER, actor_id=body.actor_id,
            reason=record.reason, decision_record=record,
            fact_updates=updates, revise_confirmed_facts=False,
            confirmation_dependencies=dependencies))
        deriver.progress['candidate'] = None
        return {'revision': receipt.revision, 'applied_paths': len(updates),
                'study_sha256': receipt.revision_sha256}

    @router.get('/chapter-facts/residual')
    def chapter_facts_residual(project_id: str, study_definition_id: str):
        """Remaining user-decidable facts with transparent recommendations."""
        from app.protocol_workflow.agent3.chapter_facts import residual_recommendations
        current = application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id, study_definition_id))
        if current.definition is None:
            raise HTTPException(404, detail={'message': '没有找到本次研究。'})
        residual = residual_recommendations(template_loader(), current.definition)
        return {'schema_version': 'chapter-facts-residual.v1', 'residual': residual}

    @router.post('/chapter-facts/residual/confirm')
    def confirm_chapter_facts_residual(project_id: str, study_definition_id: str,
                                       body: ChapterFactsResidualConfirmRequest):
        """Apply the user-confirmed residual values as one USER decision."""
        import hashlib as _hashlib
        from app.protocol_workflow.agent3.chapter_facts import (
            residual_recommendations, RESIDUAL_RECOMMENDATIONS, _binding_index)
        from app.protocol_workflow.application.commands import (
            ApplyStudyDecisionCommand, TemplateAdoptionIntent)
        from app.protocol_workflow.canonical.hashing import canonical_json
        from packages.contracts.workbench_contracts.protocol_v3 import (
            ActorType, DecisionRecord)
        current = application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id, study_definition_id))
        if current.definition is None:
            raise HTTPException(404, detail={'message': '没有找到本次研究。'})
        if current.revision != body.expected_revision or \
                current.revision_sha256 != body.snapshot_sha256:
            raise HTTPException(409, detail={'message': '研究内容刚有更新，本次确认未执行。',
                'next_step': '请刷新页面后按最新建议重新确认。'})
        residual = residual_recommendations(template_loader(), current.definition)
        updates, retire_paths, needs_revise = {}, [], False
        for path in body.accepted_fact_paths:
            rec = residual.get(path)
            if rec is None:
                continue
            if rec.get('retire'):
                retire_paths.append(rec['canonical_path'])
                needs_revise = True
                continue
            if path not in RESIDUAL_RECOMMENDATIONS and not rec.get('revise'):
                continue
            updates[rec['canonical_path']] = rec['value']
            needs_revise = needs_revise or bool(rec.get('revise'))
        if not updates and not retire_paths:
            raise HTTPException(422, detail={'message': '没有可确认的章节事实，请刷新后重试。'})
        selected = 'chapter-facts-residual:' + _hashlib.sha256(canonical_json(
            sorted(updates)).encode()).hexdigest()[:40]
        record = DecisionRecord(
            decision_record_id='chapter.facts.residual-record:' + _hashlib.sha256(
                canonical_json([study_definition_id, body.operation_id]).encode()).hexdigest(),
            decision_key='chapter.facts.residual',
            snapshot_sha256=body.snapshot_sha256,
            expected_state_revision=body.expected_revision,
            state_revision=body.expected_revision + 1,
            option_ids=(selected,), selected_option_id=selected,
            actor_type=ActorType.USER, actor_id=body.actor_id,
            reason='确认章节组织与执行事实（AI建议值；正文中可继续修改）',
            decided_at=body.decided_at)
        command = ApplyStudyDecisionCommand(
            project_id=project_id, study_definition_id=study_definition_id,
            idempotency_key=body.operation_id, expected_revision=body.expected_revision,
            actor_type=ActorType.USER, actor_id=body.actor_id,
            reason=record.reason, decision_record=record,
            # Corrections of already-stored values carry the explicit revision
            # intent (USER actor on a CONFIRMED study); pure additions do not.
            fact_updates=updates or None, revise_confirmed_facts=needs_revise,
            template_adoption=(TemplateAdoptionIntent(
                template_id='tp_ma_07_v2', retired_fact_paths=tuple(retire_paths))
                if retire_paths else None))
        receipt = application_service.apply_decision(command)
        return {'revision': receipt.revision, 'applied_paths': len(updates),
                'retired_paths': len(retire_paths),
                'study_sha256': receipt.revision_sha256}

    @router.post('', status_code=202)
    def start(project_id: str, study_definition_id: str, body: ChapterStartRequest, tasks: BackgroundTasks):
        def execute():
            owner = manuscripts(project_id)
            state = original(owner, study_definition_id, body)
            if state is None:
                prepared = fresh(project_id, study_definition_id, body)
                if owner.run_id(prepared) != body.expected_workflow_run_id:
                    raise ValueError('manuscript_request_changed')
                state = owner.read(owner.start(prepared))
            if state['can_resume']:
                def resume():
                    try:
                        owner.resume(state['workflow_run_id'])
                    except GraphRunError as exc:
                        if exc.code != 'graph_reservation_contended_retryable':
                            raise
                tasks.add_task(resume)
            return state
        return _safe_call(lambda: checked(execute))

    @router.post('/resume', status_code=202)
    def resume(project_id: str, study_definition_id: str,
               body: ChapterStartRequest, tasks: BackgroundTasks):
        """Explicitly retry recoverable chapters without replaying the draft."""
        def execute():
            owner = manuscripts(project_id)
            state = original(owner, study_definition_id, body)
            if state is None:
                raise HTTPException(404, detail={
                    'message': '原整稿任务尚未登记，请保留本次操作记录。'})
            if state['can_resume']:
                def resume_task():
                    try:
                        owner.resume(state['workflow_run_id'])
                    except GraphRunError as exc:
                        if exc.code != 'graph_reservation_contended_retryable':
                            raise
                tasks.add_task(resume_task)
            return state
        return _safe_call(lambda: checked(execute))

    @router.post('/recover')
    def recover(project_id: str, study_definition_id: str, body: ChapterStartRequest):
        def execute():
            state = original(manuscripts(project_id), study_definition_id, body)
            if state is None:
                raise HTTPException(404, detail={'message': '原整稿任务尚未登记，请保留本次操作记录。'})
            return state
        return _safe_call(lambda: checked(execute))

    @router.post('/save/prepare')
    def prepare_save(project_id: str, study_definition_id: str, body: ChapterStartRequest):
        def execute():
            state = original(manuscripts(project_id), study_definition_id, body)
            if state is None:
                raise HTTPException(404, detail={'message': '没有找到原整稿任务。'})
            if not state['complete_candidate']:
                raise ValueError('manuscript_document_incomplete')
            return documents.current(project_id, study_definition_id)
        return _safe_call(lambda: checked(execute))

    @router.post('/save')
    def save(project_id: str, study_definition_id: str, body: ManuscriptSaveRequest):
        def execute():
            intent = body.model_dump(mode='json')
            receipt = documents.recover(project_id, study_definition_id, body.expected_workflow_run_id, intent)
            if receipt is not None:
                return receipt
            owner = manuscripts(project_id)
            if original(owner, study_definition_id, body) is None:
                raise HTTPException(404, detail={'message': '没有找到原整稿任务。'})
            return documents.save(project_id, study_definition_id, owner, body.expected_workflow_run_id, intent)
        return _safe_call(lambda: checked(execute))

    @router.post('/save/recover')
    def recover_save(project_id: str, study_definition_id: str, body: ManuscriptSaveRequest):
        def execute():
            receipt = documents.recover(project_id, study_definition_id, body.expected_workflow_run_id, body.model_dump(mode='json'))
            if receipt is None:
                raise HTTPException(404, detail={'message': '尚未找到本次初稿保存记录，原生成内容已保留。'})
            return receipt
        return _safe_call(lambda: checked(execute))

    class ManuscriptEditRequest(ManuscriptSaveRequest):
        edits: list[dict] = Field(min_length=1)

    @router.post('/edits')
    def apply_edits(project_id: str, study_definition_id: str, body: ManuscriptEditRequest):
        """Free working-draft edits (R3): every edit saves as a new version."""
        def execute():
            study = application_service.get_study_definition(
                GetStudyDefinitionQuery(project_id, study_definition_id))
            if study.definition is None:
                raise HTTPException(404, detail={'message': '没有找到本次研究。'})
            result = documents.edit(project_id, study_definition_id,
                study.definition.facts, body.model_dump(mode='json'))
            return result
        return _safe_call(lambda: checked(execute))

    @router.get('/synopsis-candidate')
    def synopsis_candidate(project_id: str, study_definition_id: str):
        """Deterministic synopsis projection as a visible candidate (T11/R4).

        Initial-generation aid and explicit refresh only — nothing here
        writes into the working draft by itself; applying goes through the
        user's edit or a scoped object revision.
        """
        current = application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id, study_definition_id))
        if current.definition is None:
            raise HTTPException(404, detail={'message': '没有找到本次研究。'})
        from app.protocol_workflow.agent3.synopsis_projection import build_synopsis_blocks
        blocks = build_synopsis_blocks(current.definition.facts)
        return {'schema_version': 'synopsis-candidate.v1',
            'basis': '按已确认事实确定性投影，供初次生成或显式刷新核对；不自动写入正文。',
            'blocks': blocks}

    @router.get('/soa-candidate')
    def soa_candidate(project_id: str, study_definition_id: str):
        """Deterministic visit×assessment matrix as a visible candidate (T11)."""
        current = application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id, study_definition_id))
        if current.definition is None:
            raise HTTPException(404, detail={'message': '没有找到本次研究。'})
        from app.protocol_workflow.agent3.soa_matrix import soa_table_content, soa_summary
        content = soa_table_content(current.definition.facts)
        return {'schema_version': 'soa-candidate.v1',
            'basis': '访视×评估矩阵按已确认事实确定性投影；可应用于SOA章或用于一致性核对。',
            'available': content is not None,
            'summary': soa_summary(current.definition.facts),
            'content': content}

    @router.get('/reconciliation')
    def reconciliation_view(project_id: str, study_definition_id: str):
        """Snapshot-bound reconciliation for the saved working draft (T09)."""
        current = application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id, study_definition_id))
        if current.definition is None:
            raise HTTPException(404, detail={'message': '没有找到本次研究。'})
        view = documents.reconciliation(project_id, study_definition_id,
            current.definition.facts, current.revision_sha256)
        if view is None:
            raise HTTPException(404, detail={'message': '尚未保存完整工作初稿，先保存再核对。'})
        return view

    class ReconciliationResolveRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        operation_id: NonEmptyText
        actor_id: NonEmptyText
        expected_revision: int
        semantic_block_id: str = ''
        decision: str = 'accepted'

    @router.post('/reconciliation/resolve')
    def resolve_reconciliation(project_id: str, study_definition_id: str,
                               body: ReconciliationResolveRequest):
        """Acknowledge a difference for the current document revision only."""
        def execute():
            current = application_service.get_study_definition(
                GetStudyDefinitionQuery(project_id, study_definition_id))
            if current.definition is None:
                raise HTTPException(404, detail={'message': '没有找到本次研究。'})
            intent = body.model_dump(mode='json')
            # F06: the acknowledgement binds to the study version it was
            # given on — a later study change reopens the difference.
            intent['study_revision_sha256'] = current.revision_sha256
            return documents.resolve_reconciliation(project_id, study_definition_id, intent)
        return _safe_call(lambda: checked(execute))

    class ObjectRevisionRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        operation_id: NonEmptyText
        actor_id: StableId
        expected_revision: int
        expected_document_sha256: Sha256
        semantic_block_id: NonEmptyText
        expected_content_sha256: str = ''
        scope: str = 'replace_object'
        instruction: str = ''
        candidate_content: str = ''
        # F07: patch_object 的授权子范围——表格 {kind:'table_cell',row,column}
        # 或段落 {kind:'text_range',start,end}；服务端据此约束应用范围。
        target: dict | None = None

    class OfficeSelectionRevisionRequest(BaseModel):
        """One AI candidate for a live GenOffice text selection.

        The server produces text only. The browser editor owns the live anchor,
        baseline comparison, apply and undo so an old semantic document can
        never overwrite the current Office working copy.
        """
        model_config = ConfigDict(extra='forbid')
        operation_id: StableId
        actor_id: StableId
        anchor_id: NonEmptyText
        target_kind: str = Field(pattern='^(paragraph|table_cell)$')
        selected_text: str = Field(min_length=1, max_length=20000)
        instruction: str = Field(min_length=1, max_length=4000)
        office_artifact_revision: int = Field(ge=0, strict=True)

    def _object_target(project_id, study_definition_id, block_id, body):
        intent = body.model_dump(mode='json')
        intent['semantic_block_id'] = block_id
        return intent

    class OfficeSnapshotRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        operation_id: NonEmptyText
        actor_id: NonEmptyText
        expected_revision: int
        expected_document_sha256: Sha256
        content_base64: str = ''
        # 审计 G1/F04：编辑器打开时所基于的 Office 工作副本版本；条件写基线。
        base_artifact_revision: int | None = None
        # 审计 G1/F05：打开时观察到的 StudyDefinition 版本；保存时另记录
        # 当时观察到的 current，旧稿不被贴上较新研究版本。
        opened_study_revision_sha256: Sha256 | None = None

    @router.post('/office-draft/snapshots', status_code=201)
    def save_office_snapshot(project_id: str, study_definition_id: str,
                             body: OfficeSnapshotRequest):
        """Persist one immutable Office working copy bound to this revision (T10)."""
        def execute():
            current = application_service.get_study_definition(
                GetStudyDefinitionQuery(project_id, study_definition_id))
            if current.definition is None:
                raise HTTPException(404, detail={'message': '没有找到本次研究。'})
            intent = body.model_dump(mode='json')
            # The draft's own research baseline stays what the editor opened
            # with; the current observation is recorded separately so an old
            # working copy is never silently re-labelled as S2 (F05).
            intent['study_revision_sha256'] = (
                body.opened_study_revision_sha256 or current.revision_sha256)
            intent['study_revision_sha256_current_observed'] = current.revision_sha256
            try:
                return documents.office_snapshot(project_id, study_definition_id, intent)
            except OfficeWorkingCopyConflictError as exc:
                raise HTTPException(status_code=409, detail={
                    'code': 'manuscript_office_base_conflict',
                    'message': '这份工作副本在您编辑期间已被另一窗口保存了新版本，本次未覆盖；'
                        '请刷新查看最新版本后再决定如何合并。',
                    'latest_snapshot': exc.latest_receipt,
                }) from exc
        return _safe_call(lambda: checked(execute))

    @router.post('/office-draft/snapshots/{operation_id}/recover')
    def recover_office_snapshot(project_id: str, study_definition_id: str,
                                operation_id: str, body: OfficeSnapshotRequest):
        def execute():
            intent = body.model_dump(mode='json')
            receipt = documents.recover_office_snapshot(project_id, study_definition_id, intent)
            if receipt is None:
                raise HTTPException(404, detail={'message': '没有找到该快照操作记录，可安全重试。'})
            return receipt
        return _safe_call(lambda: checked(execute))

    @router.get('/office-draft/snapshots')
    def office_snapshot_history(project_id: str, study_definition_id: str):
        return {'snapshots': documents.office_snapshot_history(project_id, study_definition_id)}

    @router.get('/office-draft/snapshots/latest')
    def latest_office_snapshot(project_id: str, study_definition_id: str):
        latest = documents.latest_office_snapshot(project_id, study_definition_id)
        if latest is None:
            raise HTTPException(404, detail={'message': '尚无Office工作副本，先在编辑器中保存一次。'})
        return latest

    @router.get('/office-draft/snapshots/{operation_id}/content')
    def office_snapshot_content(project_id: str, study_definition_id: str, operation_id: str):
        from fastapi.responses import Response
        artifact = documents.office_snapshot_content(project_id, study_definition_id, operation_id)
        if artifact is None:
            raise HTTPException(404, detail={'message': '没有找到该Office工作副本。'})
        return Response(content=artifact.content,
            media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            headers={'X-Content-Sha256': artifact.metadata.content_sha256,
                # 编辑器保存时以此为 base_artifact_revision 做条件写（G1/F04）。
                'X-Artifact-Revision': str(artifact.metadata.revision)})

    @router.get('/office-draft/reconciliation')
    def office_snapshot_reconciliation(project_id: str, study_definition_id: str):
        """Read-only checks over the latest saved Word bytes; never blocks saving."""
        current = application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id, study_definition_id))
        if current.definition is None:
            raise HTTPException(404, detail={'message': '没有找到本次研究。'})
        try:
            result = documents.office_snapshot_reconciliation(
                project_id, study_definition_id, current.definition.facts,
                current.revision_sha256)
        except Exception as exc:
            raise HTTPException(422, detail={
                'message': '当前 Word 已保存，但自动核对未完成。您仍可继续编辑和下载。',
                'next_step': '可稍后重新核对，或直接人工检查当前 Word。'}) from exc
        if result is None:
            raise HTTPException(404, detail={'message': '尚无可核对的已保存 Word 工作稿。'})
        return result

    @router.post('/office-draft/ai-revisions', status_code=202)
    def prepare_office_selection_revision(project_id: str, study_definition_id: str,
                                          body: OfficeSelectionRevisionRequest,
                                          tasks: BackgroundTasks):
        """Generate a candidate for the exact live Word selection; never apply it."""
        def execute():
            current = application_service.get_study_definition(
                GetStudyDefinitionQuery(project_id, study_definition_id))
            if current.definition is None:
                raise HTTPException(404, detail={'message': '没有找到本次研究。'})
            worker = (object_revision_worker_factory(project_id, study_definition_id)
                      if object_revision_worker_factory else None)
            material = {
                'schema_version': 'office-selection-revision-input.v1',
                'project_id': project_id,
                'study_definition_id': study_definition_id,
                'study_revision_sha256': current.revision_sha256,
                **body.model_dump(mode='json'),
            }

            def run():
                try:
                    worker.run(material, operation_id=body.operation_id)
                except Exception as exc:  # noqa: BLE001 — returned by status
                    worker.progress['errors'].append(str(exc)[:200])
                    worker.progress.setdefault('errors_by_operation', {})[
                        body.operation_id] = str(exc)[:200]

            if worker is not None:
                tasks.add_task(run)
            return {
                'schema_version': 'office-selection-revision-request.v1',
                'operation_id': body.operation_id,
                'status': 'dispatched' if worker is not None else 'prepared_no_worker',
                'anchor': {
                    'anchor_id': body.anchor_id,
                    'target_kind': body.target_kind,
                    'office_artifact_revision': body.office_artifact_revision,
                },
            }
        return _safe_call(lambda: checked(execute))

    @router.get('/office-draft/ai-revisions/{operation_id}')
    def office_selection_revision_status(project_id: str, study_definition_id: str,
                                         operation_id: str):
        worker = (object_revision_worker_factory(project_id, study_definition_id)
                  if object_revision_worker_factory else None)
        if worker is None:
            return {'operation_id': operation_id, 'status': 'unavailable'}
        candidate = worker.progress.get('candidates', {}).get(operation_id)
        if candidate is not None:
            return {'operation_id': operation_id, 'status': 'candidate_ready',
                'candidate': candidate}
        if worker.progress.get('running'):
            return {'operation_id': operation_id, 'status': 'running'}
        operation_error = worker.progress.get('errors_by_operation', {}).get(operation_id)
        if operation_error:
            return {'operation_id': operation_id, 'status': 'failed',
                'message': '本次局部修改建议未生成，原文和选区未改变。'}
        return {'operation_id': operation_id, 'status': 'unknown'}

    @router.post('/objects/{block_id}/ai-revisions/prepare', status_code=202)
    def prepare_object_revision(project_id: str, study_definition_id: str, block_id: str,
                                body: ObjectRevisionRequest, tasks: BackgroundTasks):
        """Freeze the anchor, dispatch the model, apply within scope (T12)."""
        def execute():
            current = application_service.get_study_definition(
                GetStudyDefinitionQuery(project_id, study_definition_id))
            if current.definition is None:
                raise HTTPException(404, detail={'message': '没有找到本次研究。'})
            worker = (object_revision_worker_factory(project_id, study_definition_id)
                      if object_revision_worker_factory else None)
            intent = _object_target(project_id, study_definition_id, block_id, body)
            material = documents.prepare_object_revision(project_id, study_definition_id, intent)

            def run():
                try:
                    worker.run(material, operation_id=intent['operation_id'])
                except Exception as exc:  # noqa: BLE001 — surfaced via recover/poll
                    worker.progress['errors'].append(str(exc)[:200])

            if worker is not None:
                tasks.add_task(run)
            return {'schema_version': 'object-revision-request.v1',
                'operation_id': intent['operation_id'],
                'status': 'dispatched' if worker is not None else 'prepared_no_worker',
                'anchor': {'semantic_block_id': material['semantic_block_id'],
                    'document_revision': material['document_revision'],
                    'current_content_sha256': material['current_content_sha256']}}
        return _safe_call(lambda: checked(execute))

    @router.post('/objects/{block_id}/ai-revisions')
    def apply_object_revision(project_id: str, study_definition_id: str, block_id: str,
                              body: ObjectRevisionRequest):
        """Apply the scoped candidate to exactly the anchored block (A15)."""
        def execute():
            study = application_service.get_study_definition(
                GetStudyDefinitionQuery(project_id, study_definition_id))
            if study.definition is None:
                raise HTTPException(404, detail={'message': '没有找到本次研究。'})
            return documents.apply_object_revision(project_id, study_definition_id,
                study.definition.facts,
                _object_target(project_id, study_definition_id, block_id, body))
        return _safe_call(lambda: checked(execute))

    @router.post('/objects/{block_id}/ai-revisions/recover')
    def recover_object_revision(project_id: str, study_definition_id: str, block_id: str,
                                body: ObjectRevisionRequest):
        """Read-only replay lookup for a lost object-revision acknowledgement."""
        def execute():
            result = documents.recover_object_revision(project_id, study_definition_id,
                _object_target(project_id, study_definition_id, block_id, body))
            if result is None:
                raise HTTPException(404, detail={'message': '没有找到该操作记录，可安全重试或重新发起修改。'})
            return result
        return _safe_call(lambda: checked(execute))

    @router.get('/objects/{block_id}/ai-revisions/{operation_id}/status')
    def object_revision_status(project_id: str, study_definition_id: str, block_id: str,
                               operation_id: str):
        """Operation-level state for one AI revision (audit G3/F08):
        completed / running_or_unknown / unknown — never a bare 404 that
        invites a blind model re-call."""
        status = documents.object_revision_status(project_id, study_definition_id,
            block_id, operation_id)
        worker = (object_revision_worker_factory(project_id, study_definition_id)
                  if object_revision_worker_factory else None)
        candidate = (worker.progress.get('candidates', {}).get(operation_id)
                     if worker else None)
        if candidate is not None and status.get('status') != 'completed':
            return {**status, 'status': 'candidate_ready', 'candidate': candidate,
                'next_step': '请先查看候选差异，明确采用后才会修改对象。'}
        return status

    @router.post('/edits/recover')
    def recover_edits(project_id: str, study_definition_id: str, body: ManuscriptEditRequest):
        """Read-only replay lookup for a lost edit acknowledgement (B05).

        Same operation_id plus identical payload returns the original receipt;
        an unknown operation is a 404, never a new apply.
        """
        def execute():
            result = documents.recover_edit(project_id, study_definition_id,
                body.model_dump(mode='json'))
            if result is None:
                raise HTTPException(404, detail={'message': '没有找到该操作记录，可安全重试或重新编辑。'})
            return result
        return _safe_call(lambda: checked(execute))
    return router
