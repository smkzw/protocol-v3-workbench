"""Scratch, read-only: GET manuscript-plan for a PROPOSED study via real router+SQLite."""
import sys, tempfile
from pathlib import Path
sys.path[:0] = ['services/api', '.', 'tests', 'tests/protocol_v3', 'tests/protocol_v3/integration']
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory
from test_mounted_api_integration import _admitted_client, PROJECT
from test_semantic_document_reducer import _study_definition

with tempfile.TemporaryDirectory() as tmp:
    import pytest
    mp = pytest.MonkeyPatch()
    client, db = _admitted_client(Path(tmp), mp)
    factory = build_unit_of_work_factory({'backend': 'sqlite', 'path': str(db)})
    study = _study_definition(project_id=PROJECT, canonical_state='proposed', facts={'framing.study_phase': 'Ⅱ期'})
    with factory() as uow:
        uow.study_definition_cas_repository.save_with_expected_revision(PROJECT, study, 0)
        uow.commit()
    path = f'/api/projects/{PROJECT}/protocol-workflow/study-definitions/{study.study_definition_id}/manuscript-plan'
    r = client.get(path)
    print('status:', r.status_code)
    print('body:', r.text[:400])
