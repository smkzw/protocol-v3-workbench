"""Stage synthetic source/seed/design through real persistence, never a provider."""
from pathlib import Path
import sys,json
W=Path(__file__).resolve().parents[3]
for p in (W,W/'services/api',W/'tests',W/'tests/protocol_v3',W/'tests/protocol_v3/integration'):sys.path.insert(0,str(p))
R=Path(__file__).resolve().parent
if (R/'context_fixture_attempt.json').exists():raise SystemExit('Existing attempt: inspect/reuse logical keys; do not rerun this preparation.')
project='project-context-browser-fixture';db=R/'fixture.sqlite'
(R/'context_fixture_attempt.json').write_text(json.dumps({'project_id':project,'real_model_calls':0,'status':'preparing'}))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.protocol_workflow.api.composition import ProtocolWorkflowMountConfig,mount_protocol_workflow_router
from app.protocol_workflow.agent1.seed_product import create_product_seed_factory
from app.protocol_workflow.agent2.product import create_product_regimen_factory
from app.protocol_workflow.agent2.clinical_worker import prepare_regimen_request
from test_zhipu_product_transport import _FakeOpener,_FakeResponse,_completion_body
from test_clinical_design_worker import regimen
from test_writing_reference_docx import build_docx,paragraph_xml
import integration_shared as shared
shared.admit(db,project)
brief='这是完全虚构的工程验收研究，不用于临床。试验药X，合成靶点，合成症状，Ⅱ期，成人，原对照组，皮下注射。试验组与原对照组在首期第0至4周及继续期第4至8周均按以下合成规则给药：本期首次200 mg 2 mL，随后100 mg每2周一次。'
values={'research_drug':'试验药X','dosage_form_and_route':'皮下注射','anticipated_dose':'200 mg 2 mL',
    'target_or_mechanism':'合成靶点','indication':'合成症状','clinical_phase':'Ⅱ期','populations':'成人','comparator':'原对照组'}
seed_output={'fields':{k:[{'raw':v,'candidate':v,'confidence':1,'reason':'合成验收说明中的原文','basis':'user','references':[]}] for k,v in values.items()}}
seed_opener=_FakeOpener([_FakeResponse(_completion_body(content=json.dumps(seed_output)))])
kwargs=dict(storage_config={'backend':'sqlite','path':str(db)},prior_probe_receipt=W/'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',max_input_bytes=2000000,credential_resolver=lambda:'synthetic-only')
seeds=create_product_seed_factory(**kwargs,http_opener=seed_opener)
app=FastAPI();mount_protocol_workflow_router(app,ProtocolWorkflowMountConfig(enabled=True,db_path=db),seed_coordinator_factory=seeds)
base=f'/api/projects/{project}/protocol-workflow'
source_bytes=build_docx(paragraph_xml(brief));(R/'context-synthetic-source.docx').write_bytes(source_bytes)
with TestClient(app) as c:
    imported=c.post(base+'/sources',data={'logical_source_key':'context-fixture-source','source_role':'project_primary','source_version':'1.0','jurisdiction':'CN'},files={'file':('context-synthetic-source.docx',source_bytes,'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert imported.status_code==200,imported.text
    source=imported.json()['current']['source']
    started=c.post(base+'/research-intake',json={'user_brief':brief,'source_artifact_ids':[source['source_artifact_id']]})
    assert started.status_code==202,started.text
    seed_run=started.json()['workflow_run_id']
seed=seeds(project).read(seed_run);assert seed['validation']['valid'] is True,seed
prepared=prepare_regimen_request(seeds(project).prepared_request(seed_run),seed['validation']['proposal'])
unit=next(u for u in prepared.to_payload()['source_intake']['sources'][0]['units'] if u['text']==brief)
output={'coverage':[{'field':k,'index':0,'destination':'regimen.schedules','relation':'component' if k=='anticipated_dose' else 'context','reason':'合成测试输入的对应条目'} for k in values], 'regimen':regimen(),'questions':[]}
output['regimen']['input_sha256']=seed['validation']['proposal']['input_sha256']
for schedule in output['regimen']['schedules']:
    for step in schedule['steps']:step['references']=[{'source_artifact_id':source['source_artifact_id'],'locator':unit['locator'],'quote':brief}]
design_opener=_FakeOpener([_FakeResponse(_completion_body(content=json.dumps(output)))])
designs=create_product_regimen_factory(**kwargs,http_opener=design_opener)
run=designs(project).start(prepared);state=designs(project).resume(run)
assert state['status']=='ready_for_review',state
assert seed_opener.calls==1 and design_opener.calls==1
identity={'project_id':project,'seed_run_id':seed_run,'run_id':run,'actor_id':'medical_manager',
    'source_artifact_id':source['source_artifact_id'],'source_sha256':source['content_sha256'],
    'synthetic_seed_calls':1,'synthetic_regimen_calls':1,'real_model_calls':0,
    'pre_staged':'source import, seed and regimen generation; study context/adoption remain for browser'}
(R/'context_fixture.json').write_text(json.dumps(identity,ensure_ascii=False,indent=2))
(W/'frontend/tests/fixtures/study-context-fixture.json').write_text(json.dumps(identity,ensure_ascii=False,indent=2))
print(json.dumps(identity,ensure_ascii=False))
