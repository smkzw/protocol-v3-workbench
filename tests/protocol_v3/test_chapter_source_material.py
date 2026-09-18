"""Full DOCX context stays distinct from candidate body evidence."""
import hashlib
from datetime import datetime,timezone
from test_writing_reference_docx import build_docx,paragraph_xml,table_xml
from app.protocol_workflow.agent1.docx_parse import parse_docx
from packages.contracts.workbench_contracts.protocol_v3 import SourceArtifact


def material():
    toc='<w:p><w:fldSimple w:instr="TOC"><w:r><w:t>表1 合成剂量 12</w:t></w:r></w:fldSimple></w:p>'
    payload=build_docx(toc+paragraph_xml('完整原文'*3000+'最后一句')+
        table_xml([['合成项目','合成值']]).replace('<w:tc>','<w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>',1))
    source=SourceArtifact(source_artifact_id='source:chapter',logical_source_key='reference',
        content_sha256=hashlib.sha256(payload).hexdigest(),source_role='company_style_only',
        source_version='1',jurisdiction='CN',mime_type='application/docx',
        captured_at=datetime(2026,9,13,tzinfo=timezone.utc))
    return source,parse_docx(payload)


def test_full_source_roles_and_tables_survive_without_claiming_medical_quality():
    from app.protocol_workflow.agent3.source_material import prepare_chapter_source_material
    source,parsed=material()
    bundle=prepare_chapter_source_material(((source,parsed),),extracted_at=source.captured_at)
    payload=bundle.to_payload()
    assert payload['sources'][0]['parse']['blocks'][0]['role']=='derived_toc'
    assert payload['sources'][0]['parse']['blocks'][1]['text'].endswith('最后一句')
    assert payload['sources'][0]['parse']['blocks'][2]['rows'][0][0]['grid_span']==2
    assert all('表1 合成剂量' not in unit.body for unit in bundle.evidence)
    assert any(unit.body.endswith('最后一句') for unit in bundle.evidence)
    assert all(unit.source_role.value=='company_style_only' and unit.canonical_state.value=='proposed'
        and unit.quality_score==0 for unit in bundle.evidence)
    assert payload['medical_admission']=='not_assessed'
    assert bundle.input_sha256==prepare_chapter_source_material(((source,parsed),),extracted_at=source.captured_at).input_sha256
    payload['sources'][0]['parse']['blocks'][1]['text']='changed outside'
    assert bundle.to_payload()['sources'][0]['parse']['blocks'][1]['text'].endswith('最后一句')


def test_source_hash_mismatch_does_not_create_a_bundle():
    import pytest
    from dataclasses import replace
    from app.protocol_workflow.agent3.source_material import prepare_chapter_source_material
    source,parsed=material()
    with pytest.raises(ValueError,match='chapter_source_hash_mismatch'):
        prepare_chapter_source_material(((source,replace(parsed,content_sha256='f'*64)),),extracted_at=source.captured_at)


def test_chapter_prompt_contains_full_source_shape_and_the_same_evidence():
    import pytest
    from app.protocol_workflow.agent3.source_material import prepare_chapter_source_material
    from app.protocol_workflow.agent3.chapter_draft import prepare_chapter_draft
    from test_chapter_draft_request import inputs
    source,parsed=material()
    bundle=prepare_chapter_source_material(((source,parsed),),extracted_at=source.captured_at)
    contract,bound,_=inputs()
    prepared=prepare_chapter_draft(contract,bound,bundle.evidence,source_material=bundle)
    payload=prepared.to_payload()
    assert payload['source_material']['sources'][0]['parse']['blocks'][2]['rows'][0][0]['grid_span']==2
    assert payload['evidence']==bundle.to_payload()['evidence']
    with pytest.raises(ValueError,match='chapter_source_evidence_mismatch'):
        prepare_chapter_draft(contract,bound,(),source_material=bundle)


def test_numeric_and_inherited_heading_styles_are_context_not_body_evidence():
    from io import BytesIO
    from zipfile import ZipFile
    from app.protocol_workflow.agent3.source_material import prepare_chapter_source_material
    payload=build_docx(paragraph_xml('数字样式标题',style='2')+
        paragraph_xml('继承样式标题',style='custom')+paragraph_xml('可引用正文'))
    buffer=BytesIO()
    with ZipFile(BytesIO(payload)) as original, ZipFile(buffer,'w') as archive:
        for name in original.namelist():archive.writestr(name,original.read(name))
        archive.writestr('word/styles.xml', '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:style w:type="paragraph" w:styleId="2"><w:name w:val="heading 1"/>'
            '<w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>'
            '<w:style w:type="paragraph" w:styleId="custom"><w:basedOn w:val="2"/></w:style></w:styles>')
    payload=buffer.getvalue()
    source,_=material()
    source=source.model_copy(update={'content_sha256':hashlib.sha256(payload).hexdigest()})
    parsed=parse_docx(payload)
    assert [block.role for block in parsed.blocks]==['heading','heading','body']
    bundle=prepare_chapter_source_material(((source,parsed),),extracted_at=source.captured_at)
    assert [unit.body for unit in bundle.evidence]==['可引用正文']
    assert bundle.to_payload()['sources'][0]['parse']['blocks'][0]['text']=='数字样式标题'
