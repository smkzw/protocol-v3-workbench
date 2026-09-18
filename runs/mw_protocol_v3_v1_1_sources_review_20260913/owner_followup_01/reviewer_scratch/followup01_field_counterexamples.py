"""F-1 followup: fresh counterexamples for the complex-field TOC tracker (not owner's tests)."""
import sys
from io import BytesIO
from zipfile import ZipFile

REPO = '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313'
for p in ('services/api', 'packages', 'tests'):
    sys.path.insert(0, REPO + '/' + p)

from app.protocol_workflow.agent1.docx_parse import parse_docx
from test_writing_reference_docx import build_docx, paragraph_xml

NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
FAIL = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (' | ' + detail if detail else ''))
    if not cond:
        FAIL.append(name)

def roles(res):
    return [b.role for b in res.blocks]

# K1: begin/instr/separate in a TEXTLESS control paragraph; empty paragraph between
# entries; end inside the last entry paragraph; following body unaffected.
xml = (
    '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText> TOC \\h \\z \\c "Table"</w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r></w:p>'
    + paragraph_xml('')  # fully empty paragraph inside the range
    + '<w:p><w:r><w:t>表1 研究流程 12</w:t></w:r></w:p>'
    + '<w:p><w:r><w:t>表2 安全性汇总 </w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    + paragraph_xml('范围之后的真实正文'))
r = parse_docx(build_docx(xml))
check('K1 empty control paragraphs keep state; end-in-entry closes range',
      roles(r) == ['derived_toc', 'derived_toc', 'body'] and not [d for d in r.diagnostics if d.code == 'field_structure_pending'],
      str(roles(r)))

# K2: unclosed TOC field -> over-label within story is visible via diagnostic, not silent
xml = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
       '<w:r><w:instrText>TOC \\o "1-3"</w:instrText></w:r></w:p>'
       + paragraph_xml('本应普通的第一段') + paragraph_xml('本应普通的第二段'))
r = parse_docx(build_docx(xml))
check('K2 unclosed field flags field_structure_pending and labels inside range',
      roles(r) == ['derived_toc', 'derived_toc']
      and any(d.code == 'field_structure_pending' for d in r.diagnostics))

# K3: story reset — unclosed TOC in document.xml must NOT leak into a header story
data = BytesIO(build_docx(
    '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText>TOC \\o "1-3"</w:instrText></w:r></w:p>'
    + paragraph_xml('范围内正文')))
with ZipFile(data, 'a') as zf:
    zf.writestr('word/header1.xml', f'<w:hdr xmlns:w="{NS}">' + paragraph_xml('页眉独立文本') + '</w:hdr>')
r = parse_docx(data.getvalue())
hdr = [b for b in r.blocks if b.role == 'header']
check('K3 story reset: header not contaminated by open document field',
      [(b.role, b.text) for b in hdr] == [('header', '页眉独立文本')]
      and any(d.code == 'field_structure_pending' and d.locator == 'word/document.xml' for d in r.diagnostics))

# K4: non-TOC complex field (PAGE) stays body evidence
xml = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
       '<w:r><w:instrText> PAGE </w:instrText></w:r>'
       '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
       '<w:r><w:t>3</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
       + paragraph_xml('后文'))
r = parse_docx(build_docx(xml))
check('K4 PAGE field result stays body', roles(r) == ['body', 'body'], str(roles(r)))

# K5: bare PAGEREF cross-reference outside any TOC stays body
xml = ('<w:p><w:r><w:t>详见第</w:t></w:r>'
       '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
       '<w:r><w:instrText> PAGEREF _Ref12345 \\h </w:instrText></w:r>'
       '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
       '<w:r><w:t>7</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>'
       '<w:r><w:t>页</w:t></w:r></w:p>')
r = parse_docx(build_docx(xml))
check('K5 bare PAGEREF stays body', roles(r) == ['body'])

# K6: fldSimple variants — lowercase TOC marked; non-TOC fldSimple stays body
xml = ('<w:p><w:fldSimple w:instr=" toc \\c Figure "><w:r><w:t>图1 结构</w:t></w:r></w:fldSimple></w:p>'
       '<w:p><w:fldSimple w:instr=" REF _Ref1 \\h "><w:r><w:t>见上文</w:t></w:r></w:fldSimple></w:p>')
r = parse_docx(build_docx(xml))
check('K6 fldSimple TOC (any case) derived; fldSimple REF body', roles(r) == ['derived_toc', 'body'], str(roles(r)))

# K7: TOC field fully inside a table cell closes there; following body unaffected
cell_toc = ('<w:tc><w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText>TOC \\c Table</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r></w:p>'
            '<w:p><w:r><w:t>表1 嵌套条目 4</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:tc>')
xml = ('<w:tbl><w:tr>' + cell_toc + '</w:tr></w:tbl>' + paragraph_xml('表后正文'))
r = parse_docx(build_docx(xml))
cell_blocks = r.blocks[0].rows[0][0].blocks
check('K7 cell-contained TOC labeled and closed inside the cell',
      [b.role for b in cell_blocks] == ['derived_toc'] and r.blocks[1].role == 'body'
      and not [d for d in r.diagnostics if d.code == 'field_structure_pending'],
      str([b.role for b in cell_blocks]))

# K8: nested PAGEREF inside TOC range (end marker standalone) — my variant
xml = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
       '<w:r><w:instrText>TOC \\o "1-3" \\h</w:instrText></w:r>'
       '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
       '<w:r><w:t>1.1 总体设计</w:t></w:r></w:p>'
       '<w:p><w:r><w:t>1.2 终点</w:t></w:r>'
       '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
       '<w:r><w:instrText> PAGEREF _Toc11 \\h </w:instrText></w:r>'
       '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>9</w:t></w:r>'
       '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
       '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
       + paragraph_xml('目录后的正文'))
r = parse_docx(build_docx(xml))
check('K8 nested PAGEREF keeps entries derived until outer end',
      roles(r) == ['derived_toc', 'derived_toc', 'body'], str(roles(r)))

# K9: split instruction fragments accumulate before classification
xml = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
       '<w:r><w:instrText>TO</w:instrText></w:r>'
       '<w:r><w:instrText>C \\h</w:instrText></w:r>'
       '<w:r><w:fldChar w:fldCharType="separate"/></w:r></w:p>'
       + '<w:p><w:r><w:t>表3 分片指令条目 2</w:t></w:r></w:p>'
       + '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
r = parse_docx(build_docx(xml))
check('K9 split instrText fragments still recognised', roles(r) == ['derived_toc'])

# K10: gallery SDT TOC behavior from pass 1 unchanged alongside new tracker
sdt = ('<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val="Table of Contents"/></w:docPartObj></w:sdtPr>'
       '<w:sdtContent>' + paragraph_xml('目录条目A 1') + '</w:sdtContent></w:sdt>')
r = parse_docx(build_docx(sdt + paragraph_xml('正文')))
check('K10 gallery SDT TOC still derived_toc', roles(r) == ['derived_toc', 'body'])

# K11: 'TOCX'/'NOTOC' instruction prefixes are not TOC
for instr in ('TOCX \\h', 'NOTOC \\h', 'TOCIOUS'):
    xml = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           f'<w:r><w:instrText>{instr}</w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r></w:p>'
           '<w:p><w:r><w:t>条目x</w:t></w:r></w:p>'
           '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    r = parse_docx(build_docx(xml))
    check(f'K11 instr "{instr}" not classified TOC', roles(r) == ['body', 'body'][:len(r.blocks)] and all(x == 'body' for x in roles(r)), str(roles(r)))

print('FAILURES:', FAIL if FAIL else 'none')
