"""Read the existing semantic manuscript without replacing study or document state."""
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory
from test_mounted_api_integration import _admitted_client, PROJECT
from test_semantic_document_reducer import _study_definition, _document_revision
from test_template_fact_adoption import _dump


def test_document_read_survives_reopen_and_reports_changed_study(tmp_path, monkeypatch):
    client, db = _admitted_client(tmp_path, monkeypatch)
    factory = build_unit_of_work_factory({'backend':'sqlite','path':str(db)})
    study = _study_definition(project_id=PROJECT)
    document = _document_revision(study)
    with factory() as uow:
        uow.study_definition_cas_repository.save_with_expected_revision(PROJECT, study, 0)
        uow.semantic_document_cas_repository.save_with_expected_revision(PROJECT, document, 0)
        uow.commit()
    path = f'/api/projects/{PROJECT}/protocol-workflow/study-definitions/{study.study_definition_id}/documents/{document.semantic_document_revision_id}'
    before = _dump(db)
    with client:
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert response.json()['document']['semantic_blocks'][0]['content'] == document.semantic_blocks[0].content
        assert response.json()['study_binding_status'] == 'current'
        assert _dump(db) == before
        missing = client.get(path.replace(study.study_definition_id, 'study:other'))
        assert missing.status_code == 404
        assert _dump(db) == before
    from app.protocol_workflow.canonical.study_definition import study_revision_hash
    advanced = _study_definition(project_id=PROJECT, revision=2,
        previous_revision_sha256=study_revision_hash(study),
        facts={**study.facts, 'picos.phase':'III'})
    with factory() as uow:
        uow.study_definition_cas_repository.save_with_expected_revision(PROJECT, advanced, 1)
        uow.commit()
    # A fresh HTTP application reads the same persisted manuscript, labels its
    # old study binding, and never silently changes the text or document version.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.protocol_workflow.api.composition import mount_protocol_workflow_router
    app = FastAPI()
    mount_protocol_workflow_router(app)
    before = _dump(db)
    with TestClient(app) as reopened:
        response = reopened.get(path)
        assert response.status_code == 200, response.text
        assert response.json()['study_binding_status'] == 'changed'
        assert response.json()['document'] == document.model_dump(mode='json')
        assert _dump(db) == before
