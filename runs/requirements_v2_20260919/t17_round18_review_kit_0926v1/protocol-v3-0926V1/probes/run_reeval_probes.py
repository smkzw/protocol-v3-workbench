import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
import reeval_excerpt as mod

conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
conn.execute('CREATE TABLE writing_reference_chapter_integration_results(tenant_id,project_id,plan_id,chapter_id,payload_json,created_at)')
for iid,cid,chunks,day in [('A','chapter1::spanA::batchA',['chunkA'],'2026-09-24'),('B','chapter1::spanB::batchB',[],'2026-09-25')]:
    row=dict(integration_id=iid,plan_id='plan1',chapter_id=cid,chunk_ids=chunks,status='completed',created_at=day,
             blocked_raw_provider_output='',integrated_chinese_text='剂量50 mg。',integrated_text_sha256='not-validated-by-this-function')
    conn.execute('INSERT INTO writing_reference_chapter_integration_results VALUES(?,?,?,?,?,?)',
                 (mod.TENANT_ID,'project1','plan1',cid,json.dumps(row),day))
chunk=SimpleNamespace(chunk_id='chunkA',status='completed',source_text='Dose 5 mg.',translated_text='剂量5 mg。',unit_targets={'1':'剂量5 mg。'})
repo=SimpleNamespace(_connect=lambda:conn,translation_chunks_for_plan=lambda *args:[chunk])
probe=mod.ReevalExcerpt();probe.repository=repo
calls=[]
mod.split_source_into_units=lambda text:[text]
mod.reconstruct_unit_map=lambda text,targets,units:targets
# Stub isolates WHICH text is sent to the checker. It does not assert correctness.
mod.evaluate_translation_fidelity_aligned_units=lambda source,target: (calls.append(dict(source=source,target=target)) or [])
chosen=probe._find_integration_for_reeval('project1','plan1','chapter1')
outcome=probe._evaluate_integration_for_reeval('project1',chosen)
new_blocked=SimpleNamespace(**{**vars(chosen),'blocked_raw_provider_output':'diagnostic text',
                              'blocked_aligned_output':'<unit1>剂量5 mg。</unit1>','chunk_ids':[]})
results=dict(kind='structural source-derived probes with explicitly stubbed checker/models',cases=[
    dict(id='R01',finding='prefix fallback picks spanA/batchA for chapter-wide group also containing spanB/batchB',selected=chosen.integration_id,selected_chapter=chosen.chapter_id),
    dict(id='R02',finding='checker receives intermediate chunk, not integrated candidate text',evaluator_outcome=outcome,
         checked=calls,candidate_not_checked=chosen.integrated_chinese_text),
    dict(id='R03',finding='new blocked_aligned_output does not itself make blocked item re-evaluable',
         evaluator_outcome=probe._evaluate_integration_for_reeval('project1',new_blocked)),
])
p=Path(__file__).resolve().parents[1]/'evidence'/'reeval_probe_results.json';p.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(results,ensure_ascii=False,indent=2))
