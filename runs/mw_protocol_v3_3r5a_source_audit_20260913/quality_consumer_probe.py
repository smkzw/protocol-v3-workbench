"""Direct validator evidence; synthetic language, no provider/service calls."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from services.api.app.ai_task_runner import AiTaskRunner
from services.api.app.medical_writing_content_quality import MedicalWritingContentQualityDetector

CASES = [
 ('consent_rule', '未提供书面知情同意者不进入筛选。', False),
 ('database_rule', '数据将在生物统计人员确认后锁定。', False),
 ('draft_sample', '样本量待医学经理确认后写入。', True),
 ('draft_missing', '主要终点的具体数值未提供。', True),
 ('draft_future', '筛选期时长将在本方案正式文本中规定。', True),
 ('followup', '试验参与者待随访期间记录相关信息。', False),
 ('joint_negative_and_draft', '未提供书面知情同意者不进入筛选；样本量待医学经理确认后写入。', True),
]

def main():
    rows=[]
    detector=MedicalWritingContentQualityDetector()
    for name,text,expected in CASES:
        findings=detector._scan_text(document=SimpleNamespace(project_id='probe',document_id='probe',version='V1'),
            section=SimpleNamespace(section_id='sec',heading='文本检查'), block={'block_id':'b'}, text=text,
            location_kind='paragraph',source_locator='synthetic:b',content_revision=0)
        output={'full_draft':{'sections':[{'section_id':'sec','proposal_text':text,'evidence_span_ids':['e1']}]},
            'evidence_spans':[{'span_id':'e1'}],'needs_medical_confirmation':True}
        errors=AiTaskRunner._validate_protocol_full_draft_output(None,output,[],{'section_ids':['sec'],'minimum_body_chars':1})
        rows.append({'case':name,'text':text,'expected_draft_marker':expected,
            'detector_unresolved':any(x.rule_code=='unresolved_draft_marker' for x in findings),
            'generation_validator_unresolved':any('unresolved drafting markers' in x for x in errors),
            'generation_errors':errors})
    paths=['services/api/app/medical_writing_content_quality.py','services/api/app/ai_task_runner.py','services/api/app/medical_writing_full_draft.py']
    result={'scope':'direct existing consumers; synthetic text; no full workflow/medical acceptance',
        'source_hashes':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths},'cases':rows}
    out=Path(__file__).with_suffix('.json')
    with out.open('x') as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'cases':len(rows),'mismatches':[r['case'] for r in rows if r['generation_validator_unresolved']!=r['expected_draft_marker']]},ensure_ascii=False))
if __name__=='__main__': main()
