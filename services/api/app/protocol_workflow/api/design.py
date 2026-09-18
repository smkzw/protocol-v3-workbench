"""Design jobs derive from the stored source interpretation and pinned materials."""
import hashlib
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict, AwareDatetime, StrictInt, Field
from packages.contracts.workbench_contracts.protocol_v3 import NonEmptyText, StableId, Sha256, PositiveRevision
from app.protocol_workflow.graph import GraphRunError
from app.protocol_workflow.agent2.clinical_worker import prepare_regimen_request
from app.protocol_workflow.agent2.study_definition import prepare_regimen_adoption, prepare_regimen_recovery
from app.protocol_workflow.api.router import _safe_call, _mutation_response
from app.protocol_workflow.api.schemas import StudyDefinitionMutationResponse
from app.protocol_workflow.application.research_context import prepare_research_context_creation, prepare_research_context_update
from app.protocol_workflow.application.queries import ListStudyDefinitionsQuery, RecoverStudyDecisionQuery, GetStudyDefinitionQuery


class RegimenStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed_run_id: NonEmptyText
    study_definition_id: StableId | None = None
    expected_workflow_run_id: NonEmptyText | None = None


class RegimenAdoptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    study_definition_id: StableId
    operation_id: StableId
    expected_revision: PositiveRevision
    snapshot_sha256: Sha256
    actor_id: StableId
    decided_at: AwareDatetime
    reason: NonEmptyText


class ResearchInformationRequest(RegimenAdoptionRequest):
    seed_run_id: NonEmptyText
    selections: dict[str, StrictInt]
    user_edits: dict[str, NonEmptyText | list[NonEmptyText]] = Field(default_factory=dict)


class ResearchContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed_run_id: NonEmptyText
    operation_id: StableId
    actor_id: StableId
    decided_at: AwareDatetime


class ResearchContextUpdateRequest(ResearchContextRequest):
    expected_revision: PositiveRevision
    snapshot_sha256: Sha256


def create_design_router(seeds, designs, *, application_service, route_class):
    router = APIRouter(prefix="/api/projects/{project_id}/protocol-workflow/design/regimen",
                       tags=["方案设计建议"],route_class=route_class)
    def current(coordinator, run_id):
        try:
            return coordinator.read(run_id)
        except GraphRunError as exc:
            if exc.code in {"graph_run_unknown","graph_plan_binding_mismatch"}:
                raise HTTPException(404,detail={"message":"没有找到本次设计记录。","next_step":"请返回本项目已保存的资料整理结果。"}) from exc
            raise
    def prepared(project_id, seed_run_id):
        seed = seeds(project_id)
        state = current(seed,seed_run_id)
        validation = state.get("validation")
        if not validation or not validation.get("valid"):
            raise HTTPException(409,detail={"message":"资料整理结果尚不可用于设计。","next_step":"请先查看本次资料整理进度或处理已有提示。"})
        return prepare_regimen_request(seed.prepared_request(seed_run_id),validation["proposal"])
    def schedule(coordinator,state,tasks):
        if state["can_resume"]:
            def resume():
                try:
                    coordinator.resume(state["workflow_run_id"])
                except GraphRunError as exc:
                    if exc.code != "graph_reservation_contended_retryable":
                        raise
            tasks.add_task(resume)
    def target_request(project_id, body):
        request = prepared(project_id, body.seed_run_id)
        if body.study_definition_id is not None:
            from app.protocol_workflow.agent2.study_input import bind_regimen_study_input
            from app.protocol_workflow.agent2.input_context import regimen_input_context
            study = _safe_call(lambda: application_service.get_study_definition(
                GetStudyDefinitionQuery(project_id, body.study_definition_id)))
            if study.definition is None:
                raise HTTPException(404, detail={"message":"没有找到本次研究。"})
            if study.definition.facts.get('research.input_context') != regimen_input_context(request):
                raise HTTPException(409, detail={"message":"当前研究所用资料已变化，请先核对资料。"})
            request = bind_regimen_study_input(request, study_definition_id=body.study_definition_id,
                                              facts=study.definition.facts)
        return request

    def original_state(project_id, body, coordinator):
        if not body.expected_workflow_run_id:
            return None
        try:
            original = coordinator.prepared_request(body.expected_workflow_run_id)
        except GraphRunError as exc:
            if exc.code == 'graph_run_unknown':
                return None
            raise
        source = prepared(project_id, body.seed_run_id)
        payload = original.to_payload()
        if (payload['seed_proposal'] != source.to_payload()['seed_proposal']
            or (payload.get('confirmed_study') or {}).get('study_definition_id') != body.study_definition_id):
            raise HTTPException(409, detail={"message":"保存的任务与本次研究不一致，请核对原记录。"})
        return current(coordinator, body.expected_workflow_run_id)

    @router.post('/prepare')
    def prepare_design(project_id: str, body: RegimenStartRequest):
        request = target_request(project_id, body)
        return {"seed_run_id": body.seed_run_id, "study_definition_id": body.study_definition_id,
                "expected_workflow_run_id": designs(project_id).run_id(request)}

    @router.post("",status_code=202)
    def start(project_id:str,body:RegimenStartRequest,background_tasks:BackgroundTasks):
        coordinator = designs(project_id)
        existing = original_state(project_id, body, coordinator)
        if existing is not None:
            schedule(coordinator, existing, background_tasks)
            return existing
        request = target_request(project_id, body)
        if body.expected_workflow_run_id and coordinator.run_id(request) != body.expected_workflow_run_id:
            raise HTTPException(409, detail={"message":"研究内容已更新，本次尚未开始生成，请核对后再继续。"})
        state = coordinator.read(coordinator.start(request))
        schedule(coordinator,state,background_tasks)
        return state
    @router.post("/recover")
    def recover(project_id:str,body:RegimenStartRequest):
        coordinator = designs(project_id)
        if body.expected_workflow_run_id:
            state = original_state(project_id, body, coordinator)
            if state is None:
                raise HTTPException(404, detail={"message":"尚未找到原设计任务，资料与原操作已保留。"})
            return state
        request = target_request(project_id, body)
        return current(coordinator,coordinator.run_id(request))
    def context_command(project_id, body):
        study_id = "study:v3:" + hashlib.sha256(project_id.encode()).hexdigest()[:32]
        return prepare_research_context_creation(project_id=project_id, study_definition_id=study_id,
            seed_run_id=body.seed_run_id, prepared=prepared(project_id,body.seed_run_id),
            operation_id=body.operation_id, actor_id=body.actor_id, decided_at=body.decided_at)

    def context_query(command):
        return RecoverStudyDecisionQuery(project_id=command.project_id,
            study_definition_id=command.study_definition_id, idempotency_key=command.idempotency_key,
            decision_record=command.decision_record)

    @router.get("/study-context")
    def list_contexts(project_id:str,seed_run_id:str|None=None):
        from app.protocol_workflow.agent2.input_context import regimen_input_context
        expected = None if seed_run_id is None else _safe_call(lambda: regimen_input_context(prepared(project_id,seed_run_id)))
        values = _safe_call(lambda: application_service.list_study_definitions(ListStudyDefinitionsQuery(project_id)))
        return {"studies": [{"study_definition_id": value.definition.study_definition_id,
            "revision": value.revision, "revision_sha256": value.revision_sha256,
            "input_context": value.definition.facts.get("research.input_context"),
            "matches_selected_inputs": expected is not None and value.definition.facts.get("research.input_context") == expected}
            for value in values]}

    @router.post("/study-context",response_model=StudyDefinitionMutationResponse)
    def create_context(project_id:str,body:ResearchContextRequest):
        def execute():
            command = context_command(project_id,body)
            existing = application_service.list_study_definitions(ListStudyDefinitionsQuery(project_id))
            if existing:
                if any(value.definition.study_definition_id == command.study_definition_id for value in existing):
                    found = application_service.lookup_decision(context_query(command))
                    if found is not None:
                        return found
                raise HTTPException(409,detail={"message":"本项目已有研究，原内容已保留。",
                    "next_step":"请读取当前研究，再使用本次资料继续。"})
            return application_service.create_study_definition(command)
        return _mutation_response(_safe_call(execute))

    @router.post("/study-context/recover",response_model=StudyDefinitionMutationResponse)
    def recover_context(project_id:str,body:ResearchContextRequest):
        result = _safe_call(lambda: application_service.lookup_decision(context_query(context_command(project_id,body))))
        if result is None:
            raise HTTPException(404,detail={"message":"尚未查到本次写作任务的保存回执。",
                "next_step":"请保留原操作并先核对，不要重复新建研究。"})
        return _mutation_response(result)

    def input_update_command(project_id,study_id,body):
        return prepare_research_context_update(project_id=project_id,study_definition_id=study_id,
            prepared=prepared(project_id,body.seed_run_id),**body.model_dump())

    @router.post("/study-context/{study_id}/inputs",response_model=StudyDefinitionMutationResponse)
    def update_inputs(project_id:str,study_id:str,body:ResearchContextUpdateRequest):
        return _mutation_response(_safe_call(lambda: application_service.apply_decision(input_update_command(project_id,study_id,body))))

    @router.post("/study-context/{study_id}/inputs/recover",response_model=StudyDefinitionMutationResponse)
    def recover_inputs(project_id:str,study_id:str,body:ResearchContextUpdateRequest):
        result = _safe_call(lambda: application_service.lookup_decision(context_query(input_update_command(project_id,study_id,body))))
        if result is None:
            raise HTTPException(404,detail={"message":"尚未查到本次资料选择的保存回执。",
                "next_step":"请先核对原操作，不要重复提交。"})
        return _mutation_response(result)

    def information_receipt(project_id, body):
        from app.protocol_workflow.agent2.research_intent import research_intent_record
        record = research_intent_record(seeds(project_id), **body.model_dump())
        return application_service.lookup_decision(RecoverStudyDecisionQuery(
            project_id=project_id, study_definition_id=body.study_definition_id,
            idempotency_key=body.operation_id, decision_record=record))

    @router.post('/research-information', response_model=StudyDefinitionMutationResponse)
    def adopt_information(project_id: str, body: ResearchInformationRequest):
        def execute():
            receipt = information_receipt(project_id, body)
            if receipt is not None:
                return receipt
            study = application_service.get_study_definition(GetStudyDefinitionQuery(project_id, body.study_definition_id))
            if study.definition is None:
                raise HTTPException(404, detail={"message":"没有找到本次研究，原选择已保留。"})
            from app.protocol_workflow.agent2.input_context import regimen_input_context
            context = regimen_input_context(prepared(project_id, body.seed_run_id))
            if study.definition.facts.get('research.input_context') != context:
                raise HTTPException(409, detail={"message":"本次研究资料已变化，尚未保存这组选择。",
                    "next_step":"请核对当前资料整理出的研究信息。"})
            from app.protocol_workflow.agent2.research_intent import prepare_research_intent_adoption
            try:
                command = prepare_research_intent_adoption(seeds(project_id), **body.model_dump())
            except ValueError as exc:
                raise HTTPException(422, detail={"message":"研究信息选择尚不完整，本次未保存。",
                    "next_step":"请选择当前显示的研究信息建议。"}) from exc
            return application_service.apply_decision(command)
        return _mutation_response(_safe_call(execute))

    @router.post('/research-information/recover', response_model=StudyDefinitionMutationResponse)
    def recover_information(project_id: str, body: ResearchInformationRequest):
        receipt = _safe_call(lambda: information_receipt(project_id, body))
        if receipt is None:
            raise HTTPException(404, detail={"message":"尚未查到本次研究信息确认，原选择已保留。",
                "next_step":"请核对本次保存，不必重新整理资料。"})
        return _mutation_response(receipt)

    def seed_card_command(project_id, body):
        # Seed cards read the stored seed directly (research_intent pattern):
        # no regimen compilation and no request-level context gate — the
        # adopted card's activity is governed by its medical confirmation
        # bindings, not by this endpoint's eager validation.
        from app.protocol_workflow.agent2.design_cards import prepare_design_card_adoption
        study = application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id, body.study_definition_id))
        if study.definition is None:
            raise HTTPException(404, detail={"message": "尚未找到当前研究，原选择已保留。"})
        try:
            result = prepare_design_card_adoption(seeds(project_id), body.seed_run_id, body.card,
                selection_index=body.selection_index, user_edit=body.user_edit,
                study_definition_id=body.study_definition_id,
                operation_id=body.operation_id, expected_revision=body.expected_revision,
                snapshot_sha256=body.snapshot_sha256, actor_id=body.actor_id,
                decided_at=body.decided_at, reason=body.reason)
            return result
        except ValueError as exc:
            code = str(exc)
            if code == 'design_card_source_unresolved':
                raise HTTPException(409, detail={"message": "资料整理结果尚不可用于该卡片。",
                    "next_step": "请先查看本次资料整理进度或处理已有提示。"}) from exc
            raise HTTPException(422, detail={"message": "该卡片选择尚不完整，本次未保存。",
                "next_step": "请选择当前显示的建议选项后再确认。"}) from exc

    @router.post('/seed-card', response_model=StudyDefinitionMutationResponse)
    def adopt_seed_card(project_id: str, body: DesignCardSeedRequest):
        def execute():
            command = seed_card_command(project_id, body)
            receipt = application_service.lookup_decision(RecoverStudyDecisionQuery(
                project_id=project_id, study_definition_id=body.study_definition_id,
                idempotency_key=body.operation_id, decision_record=command.decision_record))
            if receipt is not None:
                return receipt
            return application_service.apply_decision(command)
        return _mutation_response(_safe_call(execute))

    @router.post('/seed-card/recover', response_model=StudyDefinitionMutationResponse)
    def recover_seed_card(project_id: str, body: DesignCardSeedRequest):
        command = seed_card_command(project_id, body)
        receipt = application_service.lookup_decision(RecoverStudyDecisionQuery(
            project_id=project_id, study_definition_id=body.study_definition_id,
            idempotency_key=body.operation_id, decision_record=command.decision_record))
        if receipt is None:
            raise HTTPException(404, detail={"message": "尚未查到本次确认的保存回执，原选择已保留。",
                "next_step": "请核对本次保存，不必重新整理资料。"})
        return _mutation_response(receipt)

    @router.get("/{workflow_run_id}")
    def read(project_id:str,workflow_run_id:str):
        return current(designs(project_id),workflow_run_id)
    @router.post("/{workflow_run_id}/resume",status_code=202)
    def resume(project_id:str,workflow_run_id:str,background_tasks:BackgroundTasks):
        coordinator = designs(project_id)
        state = current(coordinator,workflow_run_id)
        schedule(coordinator,state,background_tasks)
        return state
    @router.post("/{workflow_run_id}/adopt",response_model=StudyDefinitionMutationResponse)
    def adopt(project_id:str,workflow_run_id:str,body:RegimenAdoptionRequest):
        coordinator = designs(project_id)
        state = current(coordinator,workflow_run_id)
        def execute():
            current_study = application_service.get_study_definition(GetStudyDefinitionQuery(project_id,body.study_definition_id))
            if current_study.definition is None:
                raise HTTPException(404,detail={"message":"尚未找到当前研究，原建议已保留。",
                    "next_step":"请先读取或建立本次写作任务。"})
            query = prepare_regimen_recovery(coordinator,workflow_run_id,**body.model_dump())
            if query is not None:
                receipt = application_service.lookup_decision(query)
                if receipt is not None:
                    return receipt
            if state["status"] != "ready_for_review":
                raise HTTPException(409,detail={"message":"给药建议尚有未决内容，当前研究事实未改变。",
                    "next_step":"请先查看本次建议中的待处理内容。"})
            from app.protocol_workflow.agent2.input_context import regimen_input_context
            from app.protocol_workflow.agent2.study_input import validate_regimen_study_input
            original_request = coordinator.prepared_request(workflow_run_id)
            try:
                validate_regimen_study_input(original_request,
                    study_definition_id=body.study_definition_id, facts=current_study.definition.facts)
            except ValueError as exc:
                raise HTTPException(409,detail={"message":"当前研究内容与这份建议生成时不一致，本次未保存。",
                    "next_step":"请核对本研究已有内容，再处理受影响的给药建议。"}) from exc
            context = regimen_input_context(original_request)
            if current_study.definition.facts.get("research.input_context") != context:
                raise HTTPException(409,detail={"message":"这份建议使用的资料与当前研究不一致，本次未保存。",
                    "next_step":"请先核对本次研究所用资料，再查看对应建议。"})
            command = prepare_regimen_adoption(coordinator,workflow_run_id,**body.model_dump())
            return application_service.apply_decision(command)
        return _mutation_response(_safe_call(execute))
    @router.post("/{workflow_run_id}/adopt/recover",response_model=StudyDefinitionMutationResponse)
    def recover_adoption(project_id:str,workflow_run_id:str,body:RegimenAdoptionRequest):
        coordinator = designs(project_id)
        current(coordinator,workflow_run_id)
        def execute():
            query = prepare_regimen_recovery(coordinator,workflow_run_id,**body.model_dump())
            return None if query is None else application_service.lookup_decision(query)
        result = _safe_call(execute)
        if result is None:
            raise HTTPException(404,detail={"message":"尚未查到本次确认的保存回执，原方案与操作记录已保留。",
                                           "next_step":"请稍后核对本次确认，不要重新生成方案。"})
        return _mutation_response(result)
    return router


class DesignCardSeedRequest(ResearchInformationRequest):
    card: NonEmptyText
    # Seed cards use index-or-edit selection; the inherited per-field
    # selections map does not apply here.
    selections: dict[str, StrictInt] = Field(default_factory=dict)
    selection_index: StrictInt | None = None
    user_edit: NonEmptyText | None = None


class DesignElementsStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed_run_id: NonEmptyText
    study_definition_id: StableId
    expected_workflow_run_id: NonEmptyText | None = None


class DesignCardAdoptionRequest(RegimenAdoptionRequest):
    seed_run_id: NonEmptyText
    card: NonEmptyText
    selections: dict[str, NonEmptyText | StrictInt | bool]


def create_design_elements_router(seeds, element_designs, *, application_service, route_class):
    """Endpoints for the design-elements producer and its per-card adoptions."""
    router = APIRouter(prefix="/api/projects/{project_id}/protocol-workflow/design/elements",
                       tags=["方案设计要素"], route_class=route_class)

    def current(coordinator, run_id):
        try:
            return coordinator.read(run_id)
        except GraphRunError as exc:
            if exc.code in {"graph_run_unknown", "graph_plan_binding_mismatch"}:
                raise HTTPException(404, detail={"message": "没有找到本次设计要素记录。",
                    "next_step": "请返回本项目已保存的资料整理结果。"}) from exc
            raise

    def seed_validation(project_id, seed_run_id):
        state = current(seeds(project_id), seed_run_id)
        validation = state.get("validation")
        if not validation or not validation.get("valid"):
            raise HTTPException(409, detail={"message": "资料整理结果尚不可用于设计。",
                "next_step": "请先查看本次资料整理进度或处理已有提示。"})
        return validation["proposal"]

    def build_request(project_id, body, *, require_match):
        seed = seeds(project_id)
        seed.prepared_request(body.seed_run_id)
        proposal = seed_validation(project_id, body.seed_run_id)
        study = _safe_call(lambda: application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id, body.study_definition_id)))
        if study.definition is None:
            raise HTTPException(404, detail={"message": "没有找到本次研究。"})
        from app.protocol_workflow.agent2.design_workflow import prepare_design_elements_request
        request = prepare_design_elements_request(seed.prepared_request(body.seed_run_id),
            proposal, study.definition.facts)
        if require_match and body.expected_workflow_run_id \
                and element_designs(project_id).run_id(request) != body.expected_workflow_run_id:
            raise HTTPException(409, detail={"message": "研究内容已更新，本次尚未开始生成，请核对后再继续。"})
        return request

    @router.post("/prepare")
    def prepare_design(project_id: str, body: DesignElementsStartRequest):
        request = build_request(project_id, body, require_match=False)
        return {"seed_run_id": body.seed_run_id,
                "study_definition_id": body.study_definition_id,
                "expected_workflow_run_id": element_designs(project_id).run_id(request)}

    @router.post("", status_code=202)
    def start(project_id: str, body: DesignElementsStartRequest, background_tasks: BackgroundTasks):
        coordinator = element_designs(project_id)
        request = build_request(project_id, body, require_match=True)
        # start() is idempotent: an existing identical run is returned as-is.
        state = current(coordinator, coordinator.start(request))
        if state["can_resume"]:
            def resume():
                try:
                    coordinator.resume(state["workflow_run_id"])
                except GraphRunError as exc:
                    if exc.code != "graph_reservation_contended_retryable":
                        raise
            background_tasks.add_task(resume)
        return state

    @router.post("/recover")
    def recover(project_id: str, body: DesignElementsStartRequest):
        coordinator = element_designs(project_id)
        if body.expected_workflow_run_id:
            try:
                return current(coordinator, body.expected_workflow_run_id)
            except HTTPException as exc:
                if exc.status_code == 404:
                    raise HTTPException(404, detail={"message": "尚未找到原设计要素任务，资料与原操作已保留。"})
                raise
        request = build_request(project_id, body, require_match=False)
        return current(coordinator, coordinator.run_id(request))

    @router.get("/{workflow_run_id}")
    def read(project_id: str, workflow_run_id: str, study_definition_id: str | None = None):
        # Card confirmations CAS against the study revision; when the caller
        # names the study, the read carries its current revision and snapshot
        # so the client never guesses them.
        state = current(element_designs(project_id), workflow_run_id)
        if study_definition_id and state.get("status") == "ready_for_review":
            study = _safe_call(lambda: application_service.get_study_definition(
                GetStudyDefinitionQuery(project_id, study_definition_id)))
            if study.definition is not None:
                state["expected_revision"] = study.revision
                state["snapshot_sha256"] = study.revision_sha256
        return state

    @router.post("/{workflow_run_id}/resume", status_code=202)
    def resume(project_id: str, workflow_run_id: str, background_tasks: BackgroundTasks):
        coordinator = element_designs(project_id)
        state = current(coordinator, workflow_run_id)
        if state["can_resume"]:
            def resume_task():
                try:
                    coordinator.resume(state["workflow_run_id"])
                except GraphRunError as exc:
                    if exc.code != "graph_reservation_contended_retryable":
                        raise
            background_tasks.add_task(resume_task)
        return state

    def adoption_command(project_id, workflow_run_id, body):
        from app.protocol_workflow.agent2.design_adoption import prepare_design_card_adoption
        study = application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id, body.study_definition_id))
        if study.definition is None:
            raise HTTPException(404, detail={"message": "尚未找到当前研究，原建议已保留。",
                "next_step": "请先读取或建立本次写作任务。"})
        coordinator = element_designs(project_id)
        try:
            return prepare_design_card_adoption(coordinator, workflow_run_id, body.card,
                confirmed_facts=study.definition.facts, selections=dict(body.selections),
                study_definition_id=body.study_definition_id,
                operation_id=body.operation_id, expected_revision=body.expected_revision,
                snapshot_sha256=body.snapshot_sha256, actor_id=body.actor_id,
                decided_at=body.decided_at, reason=body.reason)
        except ValueError as exc:
            code = str(exc)
            if code == "design_card_not_applicable":
                raise HTTPException(409, detail={"message": "该设计要素卡片对当前研究设计不适用，本次未保存。",
                    "next_step": "请核对已确认的研究设计，再处理对应建议。"}) from exc
            raise HTTPException(422, detail={"message": f"DIAG2:{exc}",
                "next_step": "请选择当前显示的建议选项后再确认。"}) from exc

    def element_receipt(project_id, workflow_run_id, body):
        coordinator = element_designs(project_id)
        state = current(coordinator, workflow_run_id)
        output_sha = ((state.get("validation") or {}).get("raw_response") or {}).get("output_sha256")
        if not output_sha:
            return None
        from app.protocol_workflow.agent2.design_adoption import DESIGN_CARDS
        spec = DESIGN_CARDS.get(body.card)
        if spec is None:
            raise HTTPException(422, detail={"message": "没有找到该设计要素卡片。"})
        from app.protocol_workflow.canonical.hashing import canonical_json
        from app.protocol_workflow.application.queries import RecoverStudyDecisionQuery
        option = 'design-element-option:' + hashlib.sha256(canonical_json(
            [workflow_run_id, output_sha, body.card]).encode()).hexdigest()
        identity = spec['decision_key'] + '-record:' + hashlib.sha256(canonical_json(
            [project_id, body.study_definition_id, body.operation_id]).encode()).hexdigest()
        from packages.contracts.workbench_contracts.protocol_v3 import ActorType, DecisionRecord
        record = DecisionRecord(decision_record_id=identity, decision_key=spec['decision_key'],
            snapshot_sha256=body.snapshot_sha256, expected_state_revision=body.expected_revision,
            state_revision=body.expected_revision + 1, option_ids=(option,),
            selected_option_id=option, actor_type=ActorType.USER, actor_id=body.actor_id,
            reason=body.reason, decided_at=body.decided_at)
        return application_service.lookup_decision(RecoverStudyDecisionQuery(
            project_id=project_id, study_definition_id=body.study_definition_id,
            idempotency_key=body.operation_id, decision_record=record))

    @router.post("/{workflow_run_id}/adopt/{card}", response_model=StudyDefinitionMutationResponse)
    def adopt_card(project_id: str, workflow_run_id: str, card: str,
                   body: DesignCardAdoptionRequest):
        if body.card != card:
            raise HTTPException(422, detail={"message": "请求路径与内容中的卡片不一致。"})
        current(element_designs(project_id), workflow_run_id)

        def execute():
            try:
                receipt = _safe_call(lambda: element_receipt(project_id, workflow_run_id, body))
            except Exception as exc:  # noqa: BLE001 — receipt probe is advisory
                import sys as _s
                print('ELEMENTS RECEIPT PROBE FAIL:', type(exc).__name__, str(exc)[:300],
                      file=_s.stderr)
                receipt = None  # fall through to a fresh apply
            if receipt is not None:
                return receipt
            command = adoption_command(project_id, workflow_run_id, body)
            try:
                return application_service.apply_decision(command)
            except Exception as exc:
                import sys as _s
                print('ELEMENTS APPLY FAIL:', type(exc).__name__, str(exc)[:400], file=_s.stderr)
                raise
        return _mutation_response(_safe_call(execute))

    @router.post("/{workflow_run_id}/adopt/{card}/recover", response_model=StudyDefinitionMutationResponse)
    def recover_card(project_id: str, workflow_run_id: str, card: str,
                     body: DesignCardAdoptionRequest):
        if body.card != card:
            raise HTTPException(422, detail={"message": "请求路径与内容中的卡片不一致。"})
        current(element_designs(project_id), workflow_run_id)
        receipt = _safe_call(lambda: element_receipt(project_id, workflow_run_id, body))
        if receipt is None:
            raise HTTPException(404, detail={"message": "尚未查到本次确认的保存回执，原建议与操作记录已保留。",
                "next_step": "请稍后核对本次确认，不要重新生成建议。"})
        return _mutation_response(receipt)

    return router
