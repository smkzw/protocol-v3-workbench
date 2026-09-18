"""Probe existing DOCX extraction behavior; no external source changes."""
import hashlib,json
from pathlib import Path
from test_writing_reference_docx import build_docx,paragraph_xml,docx_artifact
from services.api.app.writing_reference_docx import extract_docx_sections

def main():
    payload=build_docx(paragraph_xml('开始正文。')+'<w:sdt><w:sdtContent>'+paragraph_xml('此控件内包含研究终点定义。')+'</w:sdtContent></w:sdt>'+paragraph_xml('结束正文。'))
    result=extract_docx_sections(payload,docx_artifact(payload))
    data={'scope':'synthetic actual parser; not current material coverage or product acceptance',
      'source_sha256':hashlib.sha256(Path('services/api/app/writing_reference_docx.py').read_bytes()).hexdigest(),
      'expected_paragraph_count':3,'actual_texts':[s.source_text for s in result.spans],
      'controlled_paragraph_preserved':any('研究终点' in s.source_text for s in result.spans),
      'page_count':result.page_count,'physical_pages':[s.physical_page for s in result.spans],
      'parser_status':result.status}
    with Path(__file__).with_suffix('.json').open('x') as f:json.dump(data,f,ensure_ascii=False,indent=2)
    print(json.dumps(data,ensure_ascii=False))
if __name__=='__main__':main()
