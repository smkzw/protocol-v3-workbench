"""Recover exact source versions from committed storage, not filesystem latest."""
from datetime import datetime,timezone
import pytest
from test_source_identity_product import service,adopt
from test_writing_reference_docx import build_docx,paragraph_xml
from app.protocol_workflow.agent1.docx_parse import parse_docx
from app.protocol_workflow.agent1.research_seed import prepare_seed_request
from test_template_fact_adoption import _dump


@pytest.mark.parametrize("version", ["protocol-docx-xml.v1", "protocol-docx-xml.v2"])
def test_pinned_sources_read_original_bytes_after_successor_without_database_writes(tmp_path,version):
    from app.protocol_workflow.agent3.pinned_sources import read_pinned_chapter_sources
    original=build_docx(paragraph_xml('原始完整来源末句'))
    first=adopt(service(tmp_path),original)
    seed=prepare_seed_request('合成写作说明',((first.source.source,parse_docx(original,parser_version=version)),))
    adopt(service(tmp_path),build_docx(paragraph_xml('后继版本')),source_version='2')
    before=_dump(tmp_path/'product.db')
    bundle=read_pinned_chapter_sources(service(tmp_path),'project-1',seed,
        extracted_at=datetime(2026,9,13,12,tzinfo=timezone.utc))
    assert bundle.evidence[0].body=='原始完整来源末句'
    assert bundle.evidence[0].source_content_sha256==first.source.source.content_sha256
    assert _dump(tmp_path/'product.db')==before


def test_wrong_project_cannot_supply_another_projects_source_material(tmp_path):
    import pytest
    from app.protocol_workflow.agent3.pinned_sources import read_pinned_chapter_sources
    original=build_docx(paragraph_xml('合成来源'))
    first=adopt(service(tmp_path),original)
    seed=prepare_seed_request('',((first.source.source,parse_docx(original)),))
    before=_dump(tmp_path/'product.db')
    with pytest.raises(LookupError,match='chapter_source_not_found'):
        read_pinned_chapter_sources(service(tmp_path),'project-other',seed,
            extracted_at=datetime(2026,9,13,12,tzinfo=timezone.utc))
    assert _dump(tmp_path/'product.db')==before
