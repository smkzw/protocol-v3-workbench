"""Prepare full source context from the study's already selected research inputs."""
from fastapi import APIRouter,BackgroundTasks,HTTPException
from pydantic import BaseModel,ConfigDict
from packages.contracts.workbench_contracts.protocol_v3 import NonEmptyText,StableId
from app.protocol_workflow.application.queries import GetStudyDefinitionQuery
from app.protocol_workflow.agent2.clinical_worker import prepare_regimen_request
from app.protocol_workflow.agent2.input_context import regimen_input_context
from app.protocol_workflow.api.router import _safe_call
from app.protocol_workflow.graph import GraphRunError
from app.protocol_workflow.agent3.source_preparation import SourcePreparationIncomplete


class ManuscriptSourceRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    seed_run_id:NonEmptyText
    expected_workflow_run_id:NonEmptyText|None=None


class ManuscriptSourceRetryRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    retry_decision_id:StableId


def create_manuscript_source_router(seeds,preparations,*,application_service,route_class):
    router=APIRouter(prefix='/api/projects/{project_id}/protocol-workflow',
        tags=['研究方案写作'],route_class=route_class)

    def status(owner,run_id):
        try:
            progress=owner.state(run_id)
            bundle=owner.read(run_id) if progress['status']=='completed' else None
        except GraphRunError as exc:
            if exc.code in {'graph_run_unknown','graph_plan_binding_mismatch'}:
                raise HTTPException(404,detail={'message':'没有找到这次写作资料准备记录。'}) from exc
            raise
        result={**progress,'source_material_sha256':None}
        if bundle is not None:
            material=bundle.to_payload()
            result.update(source_material_sha256=bundle.input_sha256,
                source_count=len(material['sources']),assessment='not_assessed')
        return result

    def schedule(owner,state,tasks):
        if state['can_resume']:
            def execute():
                try:
                    owner.resume(state['workflow_run_id'])
                except SourcePreparationIncomplete:
                    # Failure is already durable and visible through GET.
                    return
                except GraphRunError as exc:
                    if exc.code!='graph_reservation_contended_retryable':raise
            tasks.add_task(execute)

    def selected_input(project_id,study_definition_id,body):
        seed=seeds(project_id)
        def read_seed():
            try:
                return seed.read(body.seed_run_id)
            except GraphRunError as exc:
                if exc.code in {'graph_run_unknown','graph_plan_binding_mismatch'}:
                    raise HTTPException(404,detail={'message':'没有找到所选的资料整理记录。'}) from exc
                raise
        seed_state=_safe_call(read_seed)
        validation=seed_state.get('validation')
        if not validation or not validation.get('valid'):
            raise HTTPException(409,detail={'message':'资料整理尚未完成，请先查看当前进度。'})
        prepared=seed.prepared_request(body.seed_run_id)
        study=_safe_call(lambda:application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id,study_definition_id)))
        if study.definition is None:
            raise HTTPException(404,detail={'message':'没有找到本次研究。'})
        context=regimen_input_context(prepare_regimen_request(prepared,validation['proposal']))
        if study.definition.facts.get('research.input_context')!=context:
            raise HTTPException(409,detail={'message':'这份整理结果与本次研究所选资料不同，请核对研究资料。'})
        return prepared

    @router.post('/study-definitions/{study_definition_id}/manuscript-sources/prepare')
    def prepare_identity(project_id:str,study_definition_id:str,body:ManuscriptSourceRequest):
        prepared=selected_input(project_id,study_definition_id,body)
        return {'expected_workflow_run_id':preparations(project_id).run_id(prepared)}

    @router.post('/study-definitions/{study_definition_id}/manuscript-sources',status_code=202)
    def prepare(project_id:str,study_definition_id:str,body:ManuscriptSourceRequest,tasks:BackgroundTasks):
        prepared=selected_input(project_id,study_definition_id,body)
        owner=preparations(project_id)
        if body.expected_workflow_run_id is not None and owner.run_id(prepared)!=body.expected_workflow_run_id:
            raise HTTPException(409,detail={'message':'资料准备内容已变化，本次尚未开始，请核对当前资料。'})
        run_id=_safe_call(lambda:owner.start(prepared))
        state=status(owner,run_id)
        schedule(owner,state,tasks)
        return state

    @router.get('/manuscript-sources/{workflow_run_id}')
    def read(project_id:str,workflow_run_id:str):
        return status(preparations(project_id),workflow_run_id)

    @router.post('/manuscript-sources/{workflow_run_id}/resume',status_code=202)
    def resume(project_id:str,workflow_run_id:str,tasks:BackgroundTasks):
        owner=preparations(project_id)
        state=status(owner,workflow_run_id)
        schedule(owner,state,tasks)
        return state

    @router.post('/manuscript-sources/{workflow_run_id}/retry',status_code=202)
    def retry(project_id:str,workflow_run_id:str,body:ManuscriptSourceRetryRequest,tasks:BackgroundTasks):
        owner=preparations(project_id)
        status(owner,workflow_run_id)
        try:
            owner.start_retry(workflow_run_id,retry_decision_id=body.retry_decision_id)
        except SourcePreparationIncomplete as exc:
            raise HTTPException(409,detail={'message':'本次准备结果尚不能重试，原资料和执行记录已保留。'}) from exc
        except ValueError as exc:
            raise HTTPException(409,detail={'message':'这次重试与已保存的操作不同，请核对原准备记录。'}) from exc
        except GraphRunError as exc:
            if exc.code!='graph_root_inputs_conflict':raise
            raise HTTPException(409,detail={'message':'已有另一条恢复操作，原记录已保留，请刷新查看。'}) from exc
        state=status(owner,workflow_run_id)
        if state['status']=='blocked':
            raise HTTPException(409,detail={'message':'本次准备结果尚不能重试，原资料和执行记录已保留。'})
        schedule(owner,state,tasks)
        return state
    return router
