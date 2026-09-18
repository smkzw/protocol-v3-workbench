"""Mounted product route and persistent source bytes, without a listening server."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import integration_shared as shared
from test_writing_reference_docx import build_docx, paragraph_xml
from app.protocol_workflow.api.composition import ProtocolWorkflowMountConfig, mount_protocol_workflow_router

PROJECT = 'project-source-import'
BASE = f'/api/projects/{PROJECT}/protocol-workflow/sources'


def client(db):
    app = FastAPI()
    assert mount_protocol_workflow_router(app, ProtocolWorkflowMountConfig(enabled=True, db_path=db))
    return TestClient(app)


def upload(c, payload, version='1.0'):
    return c.post(BASE, data={'logical_source_key': 'study-protocol',
                            'source_role': 'project_primary', 'source_version': version,
                            'jurisdiction': 'CN'},
                  files={'file': ('source.docx', payload,
                                  'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})


def test_mounted_import_reopen_parse_download_and_old_replay(tmp_path):
    db = tmp_path / 'product.db'
    shared.admit(db, PROJECT)
    original = build_docx(paragraph_xml('源文件里的研究设计。'))
    with client(db) as c:
        first = upload(c, original)
        assert first.status_code == 200, first.text
        one = first.json()
        sid = one['source']['source']['source_artifact_id']
        assert one['parse']['status'] == 'parsed_pending_source_review'
        assert one['medical_admission'] == 'pending'
        second = upload(c, build_docx(paragraph_xml('修订后的研究设计。')), '2.0').json()
    with client(db) as reopened:
        current = reopened.get(BASE).json()['sources']
        assert current == [second['current']]
        parsed = reopened.get(f'{BASE}/{sid}/parse').json()
        assert parsed['blocks'][0]['text'] == '源文件里的研究设计。'
        assert parsed['physical_page_count'] is None
        assert reopened.get(f'{BASE}/{sid}/content').content == original
        replay = upload(reopened, original).json()
        assert replay['replayed'] and replay['current'] == second['current']


def test_bad_docx_is_explained_and_not_adopted(tmp_path):
    db = tmp_path / 'product.db'
    shared.admit(db, PROJECT)
    with client(db) as c:
        response = c.post(BASE, data={'logical_source_key': 'broken', 'source_role': 'project_primary'},
                          files={'file': ('source.docx', b'not a docx')})
        assert response.status_code == 400
        assert 'message' in response.json()['detail']
        assert c.get(BASE).json()['sources'] == []
