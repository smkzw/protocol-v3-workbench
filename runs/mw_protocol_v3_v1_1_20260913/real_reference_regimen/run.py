"""Bounded reference-only regimen extraction from the already completed seed."""
from pathlib import Path
import sys,json,hashlib
W=Path(__file__).resolve().parents[3]
for p in (W,W/'services/api'):sys.path.insert(0,str(p))
from app.protocol_workflow.agent1.seed_product import create_product_seed_factory
from app.protocol_workflow.agent2.product import create_product_regimen_factory
from app.protocol_workflow.agent2.clinical_worker import prepare_regimen_request
from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.runtime.product_profiles import select_role_registry_document
R=Path(__file__).resolve().parent
OLD=R.parent/'real_reference_intake'
if (R/'identity.json').exists():
    raise SystemExit('Existing design identity: inspect its pinned run; do not relaunch this script.')
origin=json.loads((OLD/'identity.json').read_text())
assert hashlib.sha256(Path(origin['source_path']).read_bytes()).hexdigest()==origin['source_sha256']
config={'backend':'sqlite','path':str(OLD/'reference.sqlite')}
prior=W/'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json'
def never_resolve_seed_credentials():
    raise RuntimeError('completed_seed_must_not_call_provider')
seed=create_product_seed_factory(storage_config=config,prior_probe_receipt=prior,max_input_bytes=2000000,
                                 credential_resolver=never_resolve_seed_credentials)(origin['project_id'])
state=seed.read(origin['workflow_run_id'])
assert state==json.loads((OLD/'outcome.json').read_text())
assert state['validation']['valid']
original=seed.prepared_request(origin['workflow_run_id'])
assert original.input_sha256==origin['input_sha256']
assert all(s['source_role']=='company_style_only' for s in original.to_payload()['sources'])
def seed_evidence():
    events=seed.runtime.read_events(origin['workflow_run_id'])
    return {'count':len(events),'payload_sha256':hashlib.sha256(canonical_json([e.payload for e in events]).encode()).hexdigest()}
before=seed_evidence()
prepared=prepare_regimen_request(original,state['validation']['proposal'])
role=next(r for r in select_role_registry_document().roles if r.role_id=='product-llm')
assert role.target_profile.model=='glm-5.3-flash' and role.default_effort=='max'
files=list((W/'services/api/app/protocol_workflow').rglob('*.py'))+[W/'packages/contracts/workbench_contracts/protocol_v3.py',W/'config/medical_writing/protocol_v3/skill_registry.json',W/'config/medical_writing/protocol_v3/role_registry.json']
manifest={str(p.relative_to(W)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
(R/'source_manifest.json').write_text(json.dumps(manifest,indent=2))
(R/'prepared_input.json').write_text(prepared.payload_json)
coordinator=create_product_regimen_factory(storage_config=config,prior_probe_receipt=prior,max_input_bytes=2000000)(origin['project_id'])
run_id=coordinator.start(prepared)
identity={'project_id':origin['project_id'],'workflow_run_id':run_id,'source_seed_run_id':origin['workflow_run_id'],
          'input_sha256':prepared.input_sha256,'complete_input_bytes':len(prepared.payload_json.encode()),
          'model':'glm-5.3-flash','requested_effort':'max','canonical_adoption':False,'source_scope':'historical_reference_only',
          'original_seed_before':before}
(R/'identity.json').write_text(json.dumps(identity,ensure_ascii=False,indent=2))
print(json.dumps({'status':'durably_started','workflow_run_id':run_id,'input_bytes':identity['complete_input_bytes']}),flush=True)
try:
    outcome=coordinator.resume(run_id)
except Exception as error:
    (R/'terminal_exception.json').write_text(json.dumps({'type':type(error).__name__,'code':getattr(error,'code',None),'unknown_do_not_redispatch':True}))
    raise SystemExit(2)
(R/'outcome.json').write_text(json.dumps(outcome,ensure_ascii=False,indent=2))
(R/'original_seed_unchanged.json').write_text(json.dumps({'before':before,'after':seed_evidence(),'unchanged':before==seed_evidence()},indent=2))
print(json.dumps({'status':outcome['status'],'correction_run_id':outcome['correction_run_id']}),flush=True)
