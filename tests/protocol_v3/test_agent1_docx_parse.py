"""Ordered source extraction, without manufacturing medical admission."""
from pathlib import Path
import hashlib
from io import BytesIO
from zipfile import ZipFile

from test_writing_reference_docx import build_docx, paragraph_xml, table_xml


def test_bare_toc_field_range_with_split_instruction_is_derived_until_end():
    from services.api.app.protocol_workflow.agent1.docx_parse import parse_docx

    start = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             '<w:r><w:instrText>TO</w:instrText></w:r>'
             '<w:r><w:instrText>C \\h \\c "Table"</w:instrText></w:r>'
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r></w:p>')
    nested = ('<w:p><w:r><w:t>表2 试验剂量</w:t></w:r>'
              '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
              '<w:r><w:instrText>PAGEREF _RefDose \\h</w:instrText></w:r>'
              '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
              '<w:r><w:t>21</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    end = '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    result = parse_docx(build_docx(paragraph_xml('目录前正文') + start + paragraph_xml('表1 研究设计 20')
                                   + nested + end + paragraph_xml('目录后真实研究设计')))
    assert [b.role for b in result.blocks] == ['body', 'derived_toc', 'derived_toc', 'body']
    assert [b.text for b in result.blocks] == ['目录前正文', '表1 研究设计 20', '表2 试验剂量21', '目录后真实研究设计']


def test_simple_toc_field_is_not_body_evidence():
    from services.api.app.protocol_workflow.agent1.docx_parse import parse_docx

    xml = '<w:p><w:fldSimple w:instr="TOC \\c Figure"><w:r><w:t>图1 流程</w:t></w:r></w:fldSimple></w:p>'
    assert parse_docx(build_docx(xml)).blocks[0].role == 'derived_toc'


def test_body_content_controls_keep_order_and_actual_xml_locations():
    from services.api.app.protocol_workflow.agent1.docx_parse import parse_docx
    payload = build_docx(paragraph_xml('前文') + '<w:sdt><w:sdtContent>' + paragraph_xml('控件内终点定义')
                         + '</w:sdtContent></w:sdt>' + paragraph_xml('后文'))
    result = parse_docx(payload)
    assert [b.text for b in result.blocks] == ['前文', '控件内终点定义', '后文']
    assert result.blocks[1].locator == 'word/document.xml/body/1:sdt/0:sdtContent/0:p'
    assert result.content_sha256 == hashlib.sha256(payload).hexdigest()
    assert result.physical_page_count is None
    assert result == parse_docx(payload)
    assert result.status == 'parsed_pending_source_review'


def test_toc_without_field_and_endnote_bibliography_are_distinct():
    from services.api.app.protocol_workflow.agent1.docx_parse import parse_docx
    payload = build_docx(
        '<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val="Table of Contents"/></w:docPartObj></w:sdtPr>'
        '<w:sdtContent>' + paragraph_xml('研究设计 12') + '</w:sdtContent></w:sdt>'
        '<w:sdt><w:sdtPr><w:tag w:val="EndNote.ReferenceList"/></w:sdtPr><w:sdtContent>'
        + paragraph_xml('1. Source reference.') + '</w:sdtContent></w:sdt>')
    result = parse_docx(payload)
    assert [b.role for b in result.blocks] == ['derived_toc', 'bibliography']
    assert all(b.text for b in result.blocks)


def test_toc_field_is_recognised_without_gallery_property():
    from services.api.app.protocol_workflow.agent1.docx_parse import parse_docx
    payload = build_docx('<w:sdt><w:sdtContent><w:p><w:r><w:instrText> TOC \\o "1-3" </w:instrText>'
                         '<w:t>目录条目</w:t></w:r></w:p></w:sdtContent></w:sdt>')
    assert parse_docx(payload).blocks[0].role == 'derived_toc'


def test_tables_preserve_cells_and_merge_markers_between_paragraphs():
    from services.api.app.protocol_workflow.agent1.docx_parse import parse_docx
    table = table_xml([['项目', '要求'], ['筛选', '知情同意']]).replace('<w:tc>', '<w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>', 1)
    result = parse_docx(build_docx(paragraph_xml('前') + table + paragraph_xml('后')))
    assert [b.kind for b in result.blocks] == ['paragraph', 'table', 'paragraph']
    assert result.blocks[1].rows[0][0].grid_span == 2
    assert result.blocks[1].rows[1][1].text == '知情同意'
    assert result.blocks[1].rows[1][1].locator.endswith('/1:tr/1:tc')


def test_nested_table_retains_structure_between_cell_paragraphs():
    from services.api.app.protocol_workflow.agent1.docx_parse import parse_docx
    payload = build_docx('<w:tbl><w:tr><w:tc>' + paragraph_xml('格内前文')
                         + table_xml([['嵌套项目', '嵌套值']]) + paragraph_xml('格内后文') + '</w:tc></w:tr></w:tbl>')
    result = parse_docx(payload)
    cell = result.blocks[0].rows[0][0]
    assert [b.kind for b in cell.blocks] == ['paragraph', 'table', 'paragraph']
    assert cell.blocks[1].rows[0][1].text == '嵌套值'
    assert cell.blocks[1].locator.endswith('/0:tr/0:tc/1:tbl')
    assert cell.text.count('嵌套值') == 1
    assert not result.diagnostics


def test_revision_markers_are_reported_not_silently_accepted_as_clean():
    from services.api.app.protocol_workflow.agent1.docx_parse import parse_docx
    payload = build_docx('<w:ins>' + paragraph_xml('修订中的内容') + '</w:ins>')
    result = parse_docx(payload)
    assert result.blocks[0].text == '修订中的内容'
    assert 'tracked_changes_present' in {d.code for d in result.diagnostics}
    assert result.status == 'parsed_pending_source_review'


def test_header_and_footnote_stories_keep_roles_without_fake_pages():
    from services.api.app.protocol_workflow.agent1.docx_parse import parse_docx
    data = BytesIO(build_docx(paragraph_xml('正文')))
    ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    with ZipFile(data, 'a') as archive:
        archive.writestr('word/header1.xml', f'<w:hdr xmlns:w="{ns}">' + paragraph_xml('页眉') + '</w:hdr>')
        archive.writestr('word/footnotes.xml', f'<w:footnotes xmlns:w="{ns}"><w:footnote w:id="1">'
                         + paragraph_xml('重要脚注') + '</w:footnote></w:footnotes>')
    result = parse_docx(data.getvalue())
    assert {(b.role, b.text) for b in result.blocks} == {('body', '正文'), ('header', '页眉'), ('footnote', '重要脚注')}
    assert len(result.story_parts) == 3
    assert all(b.locator.startswith('word/') for b in result.blocks)


def test_unsupported_external_chunk_is_visible_as_incomplete_source_structure():
    from services.api.app.protocol_workflow.agent1.docx_parse import parse_docx
    result = parse_docx(build_docx(paragraph_xml('正文') + '<w:altChunk/>'))
    assert any(d.code == 'external_chunk_pending' for d in result.diagnostics)


def test_existing_endnote_references_are_not_lost_inside_content_control():
    from services.api.app.protocol_workflow.agent1.docx_parse import parse_docx
    source = Path('/Users/smkzw/Documents/康哲项目资料/模版/方案模版/研究方案库/CMS-D008Ⅰ期方案-v1.0-20251212-clean.docx')
    result = parse_docx(source.read_bytes())
    references = [b for b in result.blocks if b.role == 'bibliography']
    assert len(references) == 13
    assert all('sdtContent' in b.locator for b in references)
    assert references[0].text.startswith('1.') and references[-1].text.startswith('13.')
    # Parsing this existing source does not activate a phase-I template.
    assert result.status == 'parsed_pending_source_review'
