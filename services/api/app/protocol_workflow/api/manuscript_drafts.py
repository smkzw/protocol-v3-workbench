"""One recoverable request for all applicable chapters of the current study."""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from packages.contracts.workbench_contracts.protocol_v3 import (
    AwareDateTime, NonEmptyText, StableId, Sha256)

from app.protocol_workflow.application.queries import GetStudyDefinitionQuery
from app.protocol_workflow.agent3.manuscript_request import prepare_manuscript_request, ManuscriptInputsIncomplete
from app.protocol_workflow.agent3.source_preparation import SourcePreparationIncomplete
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


class ManuscriptSaveRequest(ChapterStartRequest):
    operation_id: StableId
    actor_id: StableId
    expected_revision: int = Field(ge=0, strict=True)
    expected_document_sha256: Sha256 | None


def create_manuscript_draft_router(manuscripts, preparations, *, application_service,
        template_loader, documents, route_class, chapter_facts_deriver=None,
        chapter_facts_deriver_factory=None):
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
            if str(exc) == 'manuscript_document_incomplete':
                raise HTTPException(409, detail={'message': '完整初稿尚未生成，本次没有保存部分章节覆盖原稿。'}) from exc
            raise
        except Exception as exc:
            # Unclassified failures must not leak traces to the user, and must
            # not invite repeating a medical confirmation that already saved.
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
        """Derive missing chapter facts from the confirmed design (AI actor)."""
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
            outcome = deriver.run(template, study,
                operation_id=operation_id, expected_revision=revision,
                snapshot_sha256=snapshot)
            command = outcome.get('command')
            if command is not None:
                try:
                    application_service.apply_decision(command)
                except Exception as exc:  # noqa: BLE001 — surfaced via progress poll
                    deriver.progress['errors'].append(
                        f'apply_failed:{type(exc).__name__}:{str(exc)[:180]}')
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
        """Render the saved working draft as an ordered DOCX on the clean template."""
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
        out_dir = _Path(_tempfile.gettempdir()) / 'mw_protocol_v3_exports'
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f'manuscript-{study_definition_id.replace(":", "-")}-rev{saved["revision"]}.docx'
        current = application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id, study_definition_id))
        result = render_production_docx(template_path, template_dir, saved['document'],
            output_path, current.definition.facts if current.definition else {})
        return FileResponse(output_path, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            filename=output_path.name, headers={'X-Document-Sha256': result['document_sha256'],
                'X-Output-Sha256': result['output_sha256'], 'X-Export-Scope': result['export_scope']})

    @router.get('/chapter-facts/derive')
    def chapter_facts_status(project_id: str, study_definition_id: str):
        deriver = deriver_for(project_id, study_definition_id)
        return {'progress': dict(deriver.progress) if deriver else None}

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
