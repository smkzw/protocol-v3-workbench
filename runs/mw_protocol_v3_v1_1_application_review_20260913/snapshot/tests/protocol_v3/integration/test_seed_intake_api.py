"""Actual source router + SQLite seed graph behind the product composition."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.protocol_workflow.api.composition import ProtocolWorkflowMountConfig, mount_protocol_workflow_router
from app.protocol_workflow.agent1.seed_coordinator import SeedCoordinator
from app.protocol_workflow.agent1.seed_workflow import build_seed_runtime
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.registries import load_role_registry, load_skill_registry
from app.protocol_workflow.runtime.harness import HarnessDispatcher
from app.protocol_workflow.runtime.adapters.zhipu_api import build_zhipu_api_adapter
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory, build_committed_reservation_repository_factory
from test_seed_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body, _resolver
from test_writing_reference_docx import build_docx, paragraph_xml
from test_source_import_api import PROJECT, BASE, upload
import integration_shared as shared


def test_mounted_intake_acknowledges_durable_job_and_reuses_result(tmp_path):
    db = tmp_path / 'product.db'
    shared.admit(db, PROJECT)
    config = {'backend': 'sqlite', 'path': str(db)}
    store = LocalArtifactStore(str(db) + '.artifacts')
    role = next(r for r in load_role_registry(ROOT / 'role_registry.json').roles if r.role_kind == 'llm')
    skill = next(s for s in load_skill_registry(ROOT / 'skill_registry.json').skill_definitions()
                 if s.skill_definition_id == 'skill.research-seed-proposal')
    opener = _FakeOpener([_FakeResponse(_completion_body(content='probe')),
                          _FakeResponse(_completion_body(content='{"fields":{}}'))])
    dispatcher = HarnessDispatcher()
    def factory(project_id):
        runtime = build_seed_runtime(project_id=project_id, uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            artifact_store=store, role_entry=role, skill=skill, dispatcher=dispatcher,
            adapter_factory=lambda **kw: build_zhipu_api_adapter(credential_resolver=_resolver(),
                http_opener=opener, max_input_bytes=100_000, **kw))
        return SeedCoordinator(project_id=project_id, branch_id='main', runtime=runtime, artifact_store=store)
    def client():
        app = FastAPI()
        mount_protocol_workflow_router(app, ProtocolWorkflowMountConfig(enabled=True, db_path=db),
                                       seed_coordinator_factory=factory)
        return TestClient(app)
    endpoint = BASE.removesuffix('/sources') + '/research-intake'
    with client() as c:
        source = upload(c, build_docx(paragraph_xml('完整项目资料'))).json()['current']['source']
        body = {'user_brief': '准备方案', 'source_artifact_ids': [source['source_artifact_id']]}
        response = c.post(endpoint, json=body)
        assert response.status_code == 202, response.text
        run_id = response.json()['workflow_run_id']
        assert response.json()['status'] == 'running'
        result = c.get(endpoint + '/' + run_id)
        assert result.status_code == 200
        assert result.json()['status'] == 'needs_information'
        assert result.json()['validation']['proposal']['canonical'] == {}
        assert opener.calls == 2
    with client() as reopened:
        replay = reopened.post(endpoint, json=body)
        assert replay.status_code == 202
        assert replay.json()['workflow_run_id'] == run_id
        assert reopened.get(endpoint + '/' + run_id).json() == result.json()
        assert opener.calls == 2
        # Process stopped after initial validation but before scheduling correction.
        from app.protocol_workflow.agent1.seed_coordinator import prepare_current_seed
        from app.protocol_workflow.agent1.source_identity import SourceIdentityService
        source_service = SourceIdentityService(build_unit_of_work_factory(config), store)
        recovery_body = {**body, 'user_brief': '修复结构恢复用例'}
        prepared = prepare_current_seed(source_service, PROJECT, recovery_body['user_brief'], body['source_artifact_ids'])
        opener._outcomes.extend([
            _FakeResponse(_completion_body(content='invalid json', response_id='invalid-original')),
            _FakeResponse(_completion_body(content='{"fields":{}}', response_id='correction-restored')),
        ])
        interrupted = factory(PROJECT)
        interrupted_id = interrupted.start(prepared)
        interrupted.runtime.run_to_completion(interrupted_id)
        assert interrupted.read(interrupted_id)['status'] == 'needs_structure_correction'
        assert opener.calls == 3
        recovery = reopened.post(endpoint, json=recovery_body)
        assert recovery.status_code == 202
        assert reopened.get(endpoint + '/' + interrupted_id).json()['status'] == 'needs_information'
        assert opener.calls == 4
        upload(reopened, build_docx(paragraph_xml('新的项目资料')), '2.0')
        stale = reopened.post(endpoint, json=body)
        assert stale.status_code == 409
        assert opener.calls == 4
