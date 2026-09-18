"""Prepare selected current identities with real stored DOCX bytes."""
import pytest
from test_source_identity_product import service, adopt
from test_writing_reference_docx import build_docx, paragraph_xml


def test_selected_sources_use_exact_bytes_and_stable_selection_order(tmp_path):
    from app.protocol_workflow.agent1.seed_coordinator import prepare_current_seed
    svc = service(tmp_path)
    one = adopt(svc, build_docx(paragraph_xml('方案来源完整尾句')), logical_source_key='方案')
    two = adopt(svc, build_docx(paragraph_xml('指导原则完整尾句')), logical_source_key='指导原则', source_role='regulatory_or_guideline')
    ids = [one.current.source.source_artifact_id, two.current.source.source_artifact_id]
    a = prepare_current_seed(svc, 'project-1', '写作意图', ids)
    b = prepare_current_seed(service(tmp_path), 'project-1', '写作意图', list(reversed(ids)))
    assert a == b
    assert '方案来源完整尾句' in a.payload_json and '指导原则完整尾句' in a.payload_json
    assert 'regulatory_or_guideline' in a.payload_json
    assert len(svc.history('project-1')) == 2


def test_stale_selection_is_not_silently_replaced_by_new_source(tmp_path):
    from app.protocol_workflow.agent1.seed_coordinator import prepare_current_seed
    svc = service(tmp_path)
    old = adopt(svc, build_docx(paragraph_xml('旧版')))
    adopt(svc, build_docx(paragraph_xml('新版')), source_version='2.0')
    with pytest.raises(ValueError, match='seed_source_selection_stale'):
        prepare_current_seed(svc, 'project-1', '', [old.current.source.source_artifact_id])
    with pytest.raises(ValueError, match='seed_source_selection_stale'):
        prepare_current_seed(svc, 'project-2', '', [old.current.source.source_artifact_id])
