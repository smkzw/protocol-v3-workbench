"""Prepare, dispatch and recover a chapter pinned to its original study inputs."""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict
from packages.contracts.workbench_contracts.protocol_v3 import NonEmptyText, Sha256
from app.protocol_workflow.application.queries import GetStudyDefinitionQuery
from app.protocol_workflow.agent3.source_preparation import SourcePreparationIncomplete
from app.protocol_workflow.graph import GraphRunError
from app.protocol_workflow.registries.applicability import ApplicabilityResolutionError
from app.protocol_workflow.registries.fact_bindings import FactBindingError
from .router import _safe_call


class ChapterPreparationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_run_id: NonEmptyText
    study_revision_sha256: Sha256


class ChapterStartRequest(ChapterPreparationRequest):
    expected_workflow_run_id: NonEmptyText


def create_chapter_draft_router(drafts, preparations, *, application_service, route_class):
    router = APIRouter(prefix='/api/projects/{project_id}/protocol-workflow/study-definitions/{study_definition_id}/chapters/{node_id}/draft',
        tags=['研究方案写作'], route_class=route_class)

    def checked(fn):
        try:
            return fn()
        except GraphRunError as exc:
            if exc.code in {'graph_run_unknown', 'graph_plan_binding_mismatch'}:
                raise HTTPException(404, detail={'message': '没有找到原写作记录，已保存的资料不会重新生成。'}) from exc
            raise
        except SourcePreparationIncomplete as exc:
            raise HTTPException(409, detail={'message': '写作资料尚未准备完成，请查看原任务进度。'}) from exc
        except (ApplicabilityResolutionError, FactBindingError) as exc:
            raise HTTPException(409, detail={'message': '本节所需的研究信息还需核对，本次尚未开始写作。',
                'next_step': '请先处理研究建议中的未决或冲突内容，再继续写作。'}) from exc
        except ValueError as exc:
            code = str(exc)
            if code == 'chapter_study_missing':
                raise HTTPException(404, detail={'message': '没有找到本次研究。'}) from exc
            if code == 'chapter_node_unknown':
                raise HTTPException(404, detail={'message': '当前模板中没有找到这一章节。'}) from exc
            if code in {'chapter_not_applicable', 'applicability requires confirmed study facts'}:
                raise HTTPException(409, detail={'message': '本节尚不满足写作条件，本次没有开始生成。',
                    'next_step': '请先核对当前研究建议及本节是否适用。'}) from exc
            if code in {'chapter_study_revision_changed', 'chapter_source_context_changed', 'chapter_request_changed'}:
                raise HTTPException(409, detail={'message': '研究内容或所选资料已变化，请核对当前内容；原写作记录已保留。'}) from exc
            raise

    def fresh(project, study, node, body):
        return application_service.prepare_manuscript_chapter(GetStudyDefinitionQuery(project, study),
            node_id=node, source_preparation=preparations(project), source_run_id=body.source_run_id,
            expected_study_sha256=body.study_revision_sha256)

    def original(owner, project, node, body):
        try:
            request = owner.prepared_request(body.expected_workflow_run_id)
        except GraphRunError as exc:
            if exc.code == 'graph_run_unknown': return None
            raise
        try:
            bundle = preparations(project).read(body.source_run_id)
        except GraphRunError as exc:
            if exc.code not in {'graph_run_unknown', 'graph_plan_binding_mismatch'}: raise
            raise HTTPException(404, detail={'message': '没有找到本节所选的资料准备记录，原章节任务仍保留。'}) from exc
        if bundle is None:
            raise SourcePreparationIncomplete(preparations(project).state(body.source_run_id))
        payload = request.to_payload()
        if payload['chapter_input']['node_id'] != node or payload.get('source_material') != bundle.to_payload():
            raise ValueError('chapter_request_changed')
        return owner.read(body.expected_workflow_run_id)

    def schedule(owner, state, tasks):
        if state['can_resume']:
            def execute():
                try: owner.resume(state['workflow_run_id'])
                except GraphRunError as exc:
                    if exc.code != 'graph_reservation_contended_retryable': raise
            tasks.add_task(execute)

    @router.post('/prepare')
    def prepare(project_id: str, study_definition_id: str, node_id: str, body: ChapterPreparationRequest):
        def execute():
            request = fresh(project_id, study_definition_id, node_id, body)
            owner = drafts(project_id, study_definition_id, body.study_revision_sha256)
            return {'expected_workflow_run_id': owner.run_id(request), 'input_sha256': request.input_sha256}
        return _safe_call(lambda: checked(execute))

    @router.post('', status_code=202)
    def start(project_id: str, study_definition_id: str, node_id: str, body: ChapterStartRequest, tasks: BackgroundTasks):
        def execute():
            owner = drafts(project_id, study_definition_id, body.study_revision_sha256)
            state = original(owner, project_id, node_id, body)
            if state is None:
                request = fresh(project_id, study_definition_id, node_id, body)
                if owner.run_id(request) != body.expected_workflow_run_id:
                    raise ValueError('chapter_request_changed')
                state = owner.read(owner.start(request))
            schedule(owner, state, tasks)
            return state
        return _safe_call(lambda: checked(execute))

    @router.post('/recover')
    def recover(project_id: str, study_definition_id: str, node_id: str, body: ChapterStartRequest):
        def execute():
            owner = drafts(project_id, study_definition_id, body.study_revision_sha256)
            state = original(owner, project_id, node_id, body)
            if state is None:
                raise HTTPException(404, detail={'message': '尚未找到原写作任务，请保留本次操作记录。'})
            return state
        return _safe_call(lambda: checked(execute))
    return router
