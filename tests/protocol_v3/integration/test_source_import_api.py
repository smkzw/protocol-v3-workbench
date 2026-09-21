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


def test_metadata_can_be_corrected_without_reupload_and_stale_edit_is_explained(tmp_path):
    db = tmp_path / 'product.db'
    shared.admit(db, PROJECT)
    original = build_docx(paragraph_xml('历史方案，仅供参考。'))
    metadata = {'source_role': 'company_style_only', 'source_version': '1.3', 'jurisdiction': 'CN'}
    with client(db) as c:
        first = upload(c, original).json()
        sid = first['source']['source']['source_artifact_id']
        result = c.patch(f'{BASE}/{sid}/metadata', json=metadata)
        assert result.status_code == 200, result.text
        corrected = result.json()
        assert corrected['current']['source']['source_role'] == 'company_style_only'
        assert c.get(f'{BASE}/{sid}/content').content == original
        latest = upload(c, build_docx(paragraph_xml('后继版本。')), '2.0').json()
        replay = c.patch(f'{BASE}/{sid}/metadata', json=metadata).json()
        assert replay['replayed'] and replay['current'] == latest['current']
        conflict = c.patch(f'{BASE}/{sid}/metadata', json={**metadata, 'source_version': '1.4'})
        assert conflict.status_code == 409
        assert '新版本' in conflict.json()['detail']['message']


def test_docx_without_text_is_not_misreported_as_corrupt(tmp_path):
    db = tmp_path / 'product.db'
    shared.admit(db, PROJECT)
    # A readable OOXML body with only a visual object has no text to extract.
    source = build_docx('<w:p><w:r><w:drawing/></w:r></w:p>')
    with client(db) as c:
        response = upload(c, source)
        assert response.status_code == 400
        detail = response.json()['detail']
        assert detail['code'] == 'source_docx_no_extractable_text'
        assert '可提取的文字' in detail['message']
        assert '另存' not in detail['next_step']
        assert '文字识别' in detail['next_step']
        assert c.get(BASE).json()['sources'] == []


def test_invalid_docx_has_a_distinct_parse_error_code(tmp_path):
    db = tmp_path / 'product.db'
    shared.admit(db, PROJECT)
    with client(db) as c:
        response = upload(c, b'not a ZIP document')
        assert response.status_code == 400
        assert response.json()['detail']['code'] == 'source_docx_parse_failed'
