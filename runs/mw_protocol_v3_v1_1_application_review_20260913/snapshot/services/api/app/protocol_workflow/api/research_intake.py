"""Durable acknowledgement and read-only progress for research prefill."""
from typing import Callable
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict
from packages.contracts.workbench_contracts.protocol_v3 import NonEmptyText
from app.protocol_workflow.graph import GraphRunError
from app.protocol_workflow.agent1.seed_coordinator import SeedCoordinator, prepare_current_seed
from app.protocol_workflow.agent1.source_identity import SourceIdentityService


class ResearchIntakeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_brief: str = ''
    source_artifact_ids: list[NonEmptyText] = []


def create_research_intake_router(sources: Callable[[], SourceIdentityService],
                                  coordinators: Callable[[str], SeedCoordinator], *, route_class):
    router = APIRouter(prefix='/api/projects/{project_id}/protocol-workflow/research-intake',
                       tags=['研究方案预填'], route_class=route_class)

    @router.post('', status_code=202)
    def start(project_id: str, body: ResearchIntakeRequest, background_tasks: BackgroundTasks):
        try:
            prepared = prepare_current_seed(sources(), project_id, body.user_brief, body.source_artifact_ids)
        except ValueError as exc:
            if str(exc) == 'seed_source_selection_stale':
                raise HTTPException(409, detail={
                    'message': '所选资料已有变化，本次尚未开始整理。',
                    'next_step': '请刷新资料列表后重新选择；已保存的资料和写作说明仍可使用。',
                }) from exc
            raise
        coordinator = coordinators(project_id)
        run_id = coordinator.start(prepared)
        state = coordinator.read(run_id)
        if (state['status'] == 'running'
                or (state['status'] == 'needs_structure_correction' and state['correction_run_id'] is None)):
            background_tasks.add_task(coordinator.resume, run_id)
        return state

    @router.get('/{workflow_run_id}')
    def read(project_id: str, workflow_run_id: str):
        try:
            return coordinators(project_id).read(workflow_run_id)
        except GraphRunError as exc:
            if exc.code == 'graph_run_unknown':
                raise HTTPException(404, detail={
                    'message': '没有找到本次资料整理记录。', 'next_step': '请返回本项目的资料页面查看。',
                }) from exc
            raise

    return router
