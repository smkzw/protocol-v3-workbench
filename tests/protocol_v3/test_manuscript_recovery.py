"""Full-draft recovery keeps completed chapters while retrying one child."""
from dataclasses import dataclass
from types import SimpleNamespace
import hashlib

from app.protocol_workflow.canonical.hashing import canonical_json


@dataclass
class _Owner:
    branch_id: str = "main"

    def __post_init__(self):
        self.states = {
            "chapter-ready": {
                "status": "needs_content_review",
                "validation": {"valid": True},
                "can_resume": False,
            },
            "chapter-blocked": {
                "status": "blocked",
                "validation": None,
                "can_resume": True,
            },
        }
        self.resumed = []

    def run_id(self, request):
        return request.to_payload()["chapter_input"]["node_id"]

    def read(self, run_id):
        return {"workflow_run_id": run_id, **self.states[run_id]}

    def start(self, request):
        return self.run_id(request)

    def resume(self, run_id):
        self.resumed.append(run_id)
        self.states[run_id] = {
            "status": "needs_content_review",
            "validation": {"valid": True},
            "can_resume": False,
        }
        return self.read(run_id)


class _Runtime:
    def __init__(self, payload):
        self.payload = payload
        self.advanced = 0

    def load_run(self, plan, run_id):
        return SimpleNamespace()

    def read_events(self, run_id):
        return (SimpleNamespace(
            event_type="graph_run_started",
            payload={"root_payloads": {"manuscript_request": self.payload}},
        ),)

    def run_to_completion(self, run_id):
        self.advanced += 1


def _prepared_payload():
    plan = {
        "project_id": "project:manuscript",
        "branch_id": "main",
        "study_definition_id": "study:one",
        "study_sha256": "a" * 64,
        "chapters": [
            {"node_id": "chapter-ready", "status": "facts_ready"},
            {"node_id": "chapter-blocked", "status": "facts_ready"},
        ],
    }
    return {
        "plan": plan,
        "shared": {},
        "chapters": [
            {"chapter_input": {"node_id": "chapter-ready"}},
            {"chapter_input": {"node_id": "chapter-blocked"}},
        ],
    }


def test_blocked_child_does_not_freeze_completed_siblings():
    from app.protocol_workflow.agent3.manuscript_coordinator import ManuscriptDraftCoordinator
    from app.protocol_workflow.agent3.manuscript_request import PreparedManuscriptRequest

    payload = _prepared_payload()
    owner = _Owner()
    runtime = _Runtime(payload)
    coordinator = ManuscriptDraftCoordinator(
        project_id="project:manuscript",
        branch_id="main",
        runtime=runtime,
        chapter_factory=lambda project_id, study_id, revision: owner,
    )
    text = canonical_json(payload)
    prepared = PreparedManuscriptRequest(
        text, hashlib.sha256(text.encode()).hexdigest()
    )
    run_id = coordinator.run_id(prepared)

    state = coordinator.read(run_id)
    assert state["status"] == "running"
    assert state["can_resume"] is True
    assert state["complete_candidate"] is False
    assert [item["status"] for item in state["chapters"]] == [
        "needs_content_review", "blocked"
    ]

    finished = coordinator.resume(run_id)
    assert finished["status"] == "needs_content_review"
    assert finished["complete_candidate"] is True
    assert owner.resumed == ["chapter-blocked"]
    assert runtime.advanced == 1


def test_correction_context_uses_error_local_excerpt_for_large_output():
    from app.protocol_workflow.runtime.proposal_correction import (
        structure_correction_inputs,
    )

    content = canonical_json({
        "blocks": [{"text": "有效内容" * 6000}],
    })
    evidence = [{"evidence_unit_id": "evidence-one", "body": "原始证据"}]
    prepared_payload = {
        "chapter_input": {"node_id": "chapter-one"},
        "evidence": evidence,
        "source_material": {"evidence": evidence, "structure": "full"},
    }
    prepared = SimpleNamespace(
        input_sha256="input-sha",
        to_payload=lambda: prepared_payload,
    )
    record = {
        "content": content,
        "receipt": {
            "input_artifacts": [{"ref": "chapter-intake", "sha256": "input-sha"}],
            "output_sha256": "output-sha",
            "provider_session_id": "session:one",
            "observed_provider": "provider",
            "observed_model": "model",
            "requested_reasoning_effort": "low",
        },
    }
    validation = {
        "valid": False,
        "status": "needs_structure_correction",
        "errors": [{"code": "invalid", "location": "blocks.0.text"}],
        "raw_response": {
            "artifact_ref": "response:one",
            "output_sha256": "output-sha",
        },
    }

    corrected = structure_correction_inputs(
        prepared, record, validation, input_name="chapter_intake",
        error_prefix="chapter",
    )
    compacted = corrected["chapter_intake"]
    assert compacted["evidence"] == evidence
    assert compacted["source_material"] == {"structure": "full"}
    context = corrected["correction_context"]
    assert context["previous_output_is_excerpt"] is True
    assert len(context["previous_output"]) <= 12000


def test_nonretryable_child_does_not_prevent_untouched_sibling_from_starting():
    from app.protocol_workflow.agent3.manuscript_coordinator import ManuscriptDraftCoordinator
    from app.protocol_workflow.agent3.manuscript_request import PreparedManuscriptRequest
    from app.protocol_workflow.graph import GraphRunError
    payload = _prepared_payload()
    payload['plan']['chapters'].append({'node_id':'chapter-new','status':'facts_ready'})
    payload['chapters'].append({'chapter_input':{'node_id':'chapter-new'}})
    class Owner(_Owner):
        def __post_init__(self):
            super().__post_init__()
            self.states['chapter-blocked']['can_resume'] = False
            self.started = []
        def read(self, run_id):
            if run_id not in self.states:
                raise GraphRunError('graph_run_unknown', 'not yet started')
            return super().read(run_id)
        def start(self, request):
            run_id = self.run_id(request)
            self.started.append(run_id)
            self.states[run_id] = {'status':'running','validation':None,'can_resume':True}
            return run_id
    owner = Owner()
    runtime = _Runtime(payload)
    coordinator = ManuscriptDraftCoordinator(project_id='project:manuscript',branch_id='main',runtime=runtime,
        chapter_factory=lambda *_:owner)
    text = canonical_json(payload)
    run_id = coordinator.run_id(PreparedManuscriptRequest(text,hashlib.sha256(text.encode()).hexdigest()))
    before = coordinator.read(run_id)
    assert before['status'] == 'blocked'
    assert before['can_resume'] is True
    after = coordinator.resume(run_id)
    assert owner.started == ['chapter-new']
    assert owner.resumed == ['chapter-new']
    assert after['complete_candidate'] is False
    assert after['can_resume'] is False
    assert after['status'] == 'blocked'
    assert owner.states['chapter-blocked']['status'] == 'blocked'


def test_resume_route_schedules_original_run_but_recover_does_not():
    from fastapi import FastAPI
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient
    from app.protocol_workflow.api.manuscript_drafts import create_manuscript_draft_router
    calls = []
    prepared = SimpleNamespace(to_payload=lambda:{'plan':{'study_definition_id':'study:one','study_sha256':'a'*64},'source_run_id':'sources:one'})
    owner = SimpleNamespace(prepared_request=lambda _:prepared,
        read=lambda run:{'workflow_run_id':run,'status':'blocked','can_resume':True},
        resume=lambda run:calls.append(run))
    app = FastAPI()
    app.include_router(create_manuscript_draft_router(lambda _:owner,None,
        application_service=None,template_loader=None,documents=None,route_class=APIRoute))
    base='/api/projects/project:one/protocol-workflow/study-definitions/study:one/manuscript-draft'
    body={'source_run_id':'sources:one','study_revision_sha256':'a'*64,'expected_workflow_run_id':'run:original'}
    with TestClient(app) as client:
        assert client.post(base+'/recover',json=body).status_code == 200
        assert calls == []
        assert client.post(base+'/resume',json=body).status_code == 202
        assert calls == ['run:original']
