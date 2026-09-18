"""One recoverable request for all applicable chapters of the current study."""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import Field
from packages.contracts.workbench_contracts.protocol_v3 import StableId, Sha256

from app.protocol_workflow.application.queries import GetStudyDefinitionQuery
from app.protocol_workflow.agent3.manuscript_request import prepare_manuscript_request, ManuscriptInputsIncomplete
from app.protocol_workflow.agent3.source_preparation import SourcePreparationIncomplete
from app.protocol_workflow.graph import GraphRunError
from .chapter_drafts import ChapterPreparationRequest, ChapterStartRequest
from .router import _safe_call


class ManuscriptSaveRequest(ChapterStartRequest):
    operation_id: StableId
    actor_id: StableId
    expected_revision: int = Field(ge=0, strict=True)
    expected_document_sha256: Sha256 | None


def create_manuscript_draft_router(manuscripts, preparations, *, application_service,
        template_loader, documents, route_class):
    router = APIRouter(prefix='/api/projects/{project_id}/protocol-workflow/study-definitions/{study_definition_id}/manuscript-draft',
        tags=['研究方案写作'], route_class=route_class)

    def checked(fn):
        try:
            return fn()
        except ManuscriptInputsIncomplete as exc:
            raise HTTPException(409, detail={'message': '研究建议尚未全部确认，本次尚未开始整稿写作。',
                'next_step': '请先处理研究建议中未决或冲突的内容，已完成的确认会保留。'}) from exc
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

    @router.post('/prepare')
    def prepare(project_id: str, study_definition_id: str, body: ChapterPreparationRequest):
        def execute():
            prepared = fresh(project_id, study_definition_id, body)
            return {'expected_workflow_run_id': manuscripts(project_id).run_id(prepared),
                'input_sha256': prepared.input_sha256, 'plan': prepared.to_payload()['plan']}
        return _safe_call(lambda: checked(execute))

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

    @router.post('/edits', )
    def apply_edits(project_id: str, study_definition_id: str, body: ManuscriptEditRequest):
        """Controlled wording edits; fact-class edits return proposals, never apply."""
        def execute():
            study = application_service.get_study_definition(
                GetStudyDefinitionQuery(project_id, study_definition_id))
            if study.definition is None:
                raise HTTPException(404, detail={'message': '没有找到本次研究。'})
            result = documents.edit(project_id, study_definition_id,
                study.definition.facts, body.model_dump(mode='json'))
            return result
        return _safe_call(lambda: checked(execute))
    return router
