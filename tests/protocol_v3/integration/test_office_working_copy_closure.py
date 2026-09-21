"""Office working-copy closure: audit G1 (F04/F05/F12).

Real minimal-DOCX fixtures, a conditional write on the Office artifact
revision so two editor windows cannot silently overwrite each other, and the
study-baseline rule: an old working copy keeps the study version it was opened
against, with the save-time observation recorded separately.
"""
import base64
import hashlib
import io
import zipfile
from datetime import datetime, timezone as _tz

import pytest

from app.protocol_workflow.application.manuscript_documents import (
    ManuscriptDocumentService,
    OfficeWorkingCopyConflictError,
)
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory
from test_mounted_api_integration import PROJECT, SD_ID


def minimal_docx(body_text='工作稿正文') -> bytes:
    """A real (minimal) DOCX: a zip container with the main document part."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>')
        archive.writestr('word/document.xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body><w:p><w:r><w:t>{body_text}</w:t></w:r></w:p></w:body></w:document>')
    return buffer.getvalue()


@pytest.fixture()
def office_service(tmp_path):
    from test_manuscript_edit_control import seed_working_document
    db = tmp_path / 'product.sqlite'
    service = ManuscriptDocumentService(
        build_unit_of_work_factory({'backend': 'sqlite', 'path': str(db)}),
        clock=lambda: datetime.now(_tz.utc),
        office_store=LocalArtifactStore(str(tmp_path / 'office-artifacts')))
    seed_working_document(service, {})
    return service


def _intent(operation_id, current, docx, **extra):
    return {'operation_id': operation_id, 'actor_id': 'user:example',
        'expected_revision': current['expected_revision'],
        'expected_document_sha256': current['expected_document_sha256'],
        'content_base64': base64.b64encode(docx).decode('ascii'), **extra}


def test_fake_pk_prefix_is_rejected_as_invalid_docx(office_service):
    """F12: a bare PK-prefixed string is not a Word document — the old
    fixture that stored one must stay red."""
    current = office_service.current(PROJECT, SD_ID)
    fake = 'PK\x03\x04合成方案内容-fixture-bytes'.encode('utf-8')
    with pytest.raises(ValueError, match='manuscript_office_content_invalid'):
        office_service.office_snapshot(PROJECT, SD_ID,
            _intent('operation:fake-pk', current, fake, study_revision_sha256='sha:study'))


def test_real_docx_roundtrips_and_chains_artifact_revisions(office_service):
    current = office_service.current(PROJECT, SD_ID)
    docx = minimal_docx()
    first = office_service.office_snapshot(PROJECT, SD_ID,
        _intent('operation:office:1', current, docx, study_revision_sha256='sha:study'))
    assert first['persisted'] is True
    assert first['base_artifact_revision'] is None

    # The open path (content endpoint header contract) matches what the next
    # save pins as its base.
    artifact = office_service.office_snapshot_content(PROJECT, SD_ID, 'operation:office:1')
    assert artifact.content == docx
    assert artifact.metadata.revision == first['artifact_revision']

    second = office_service.office_snapshot(PROJECT, SD_ID,
        _intent('operation:office:2', current, minimal_docx('第二版'),
            study_revision_sha256='sha:study',
            base_artifact_revision=first['artifact_revision']))
    assert second['persisted'] is True
    assert second['artifact_revision'] != first['artifact_revision']
    assert second['base_artifact_revision'] == first['artifact_revision']


def test_stale_base_artifact_revision_conflicts_with_latest_receipt(office_service):
    """F04: two windows open the same head; the second save pins a base the
    first save has already superseded — refused with the latest receipt,
    never silent last-write-wins."""
    current = office_service.current(PROJECT, SD_ID)
    first = office_service.office_snapshot(PROJECT, SD_ID,
        _intent('operation:office:a', current, minimal_docx('窗口A'),
            study_revision_sha256='sha:study'))
    # 窗口B 保存成功推进 head。
    second = office_service.office_snapshot(PROJECT, SD_ID,
        _intent('operation:office:b', current, minimal_docx('窗口B'),
            study_revision_sha256='sha:study',
            base_artifact_revision=first['artifact_revision']))
    # 窗口A 仍以旧 base 保存 → 冲突，携带 latest 回执。
    with pytest.raises(OfficeWorkingCopyConflictError) as excinfo:
        office_service.office_snapshot(PROJECT, SD_ID,
            _intent('operation:office:a2', current, minimal_docx('窗口A重试'),
                study_revision_sha256='sha:study',
                base_artifact_revision=first['artifact_revision']))
    assert excinfo.value.latest_receipt['operation_id'] == 'operation:office:b'
    assert excinfo.value.latest_receipt['artifact_revision'] == second['artifact_revision']
    # 明确声明 base 与最新一致时（用户已刷新合并）可以继续保存。
    merged = office_service.office_snapshot(PROJECT, SD_ID,
        _intent('operation:office:a3', current, minimal_docx('窗口A合并'),
            study_revision_sha256='sha:study',
            base_artifact_revision=second['artifact_revision']))
    assert merged['persisted'] is True


def test_opened_study_baseline_is_not_relabelled_with_current(office_service):
    """F05: a draft opened against S1 and saved after the study moved to S2
    keeps S1 as its baseline; S2 is recorded only as the save-time
    observation."""
    current = office_service.current(PROJECT, SD_ID)
    receipt = office_service.office_snapshot(PROJECT, SD_ID,
        _intent('operation:office:s1', current, minimal_docx('S1底稿'),
            study_revision_sha256='sha:study:S1',
            study_revision_sha256_current_observed='sha:study:S2'))
    assert receipt['study_revision_sha256'] == 'sha:study:S1'
    assert receipt['study_revision_sha256_current_observed'] == 'sha:study:S2'
    latest = office_service.latest_office_snapshot(PROJECT, SD_ID)
    assert latest['study_revision_sha256'] == 'sha:study:S1'
    assert latest['study_revision_sha256_current_observed'] == 'sha:study:S2'


def test_two_first_editors_do_not_replace_each_others_work(office_service):
    """Both tabs opened before any snapshot; only one can create that head."""
    from concurrent.futures import ThreadPoolExecutor
    current = office_service.current(PROJECT, SD_ID)
    def save(index):
        try:
            return office_service.office_snapshot(PROJECT, SD_ID,
                _intent(f'operation:first:{index}', current, minimal_docx(f'窗口{index}'),
                        base_artifact_revision=0, study_revision_sha256='a' * 64))
        except OfficeWorkingCopyConflictError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [1, 2]))
    assert results.count('conflict') == 1
    saved = next(result for result in results if isinstance(result, dict))
    assert office_service.latest_office_snapshot(PROJECT, SD_ID)['operation_id'] == saved['operation_id']


def test_history_lists_and_downloads_both_word_versions_without_changing_head(office_service):
    from fastapi import FastAPI
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient
    from app.protocol_workflow.api.manuscript_drafts import create_manuscript_draft_router
    current=office_service.current(PROJECT,SD_ID)
    original_bytes=minimal_docx('原来的人工修改')
    first=office_service.office_snapshot(PROJECT,SD_ID,
        _intent('history:first',current,original_bytes,base_artifact_revision=0))
    second=office_service.office_snapshot(PROJECT,SD_ID,
        _intent('history:second',current,minimal_docx('后来的修改'),base_artifact_revision=first['artifact_revision']))
    app=FastAPI()
    app.include_router(create_manuscript_draft_router(None,None,application_service=None,
        template_loader=None,documents=office_service,route_class=APIRoute))
    base=f'/api/projects/{PROJECT}/protocol-workflow/study-definitions/{SD_ID}/manuscript-draft/office-draft/snapshots'
    with TestClient(app) as client:
        response=client.get(base)
        assert response.status_code==200
        versions=response.json()['snapshots']
        assert [item['operation_id'] for item in versions]==['history:second','history:first']
        assert all(item['saved_at'] for item in versions)
        original=client.get(base+'/history:first/content')
        assert original.status_code==200
        assert original.content==original_bytes
        assert client.get(base+'/latest').json()['operation_id']==second['operation_id']
