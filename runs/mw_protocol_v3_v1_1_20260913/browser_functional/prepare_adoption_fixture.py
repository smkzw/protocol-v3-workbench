"""One synthetic saved design/study for actual browser adoption; no provider IO."""
from pathlib import Path
import sys, json
W=Path(__file__).resolve().parents[3]
for p in (W,W/'services/api',W/'tests',W/'tests/protocol_v3',W/'tests/protocol_v3/integration'):sys.path.insert(0,str(p))
import integration_shared as shared
from test_clinical_design_worker import prepared_reference
from test_zhipu_product_transport import _FakeOpener,_FakeResponse,_completion_body
from app.protocol_workflow.agent2.product import create_product_regimen_factory
R=Path(__file__).resolve().parent
if (R/'adoption_fixture.json').exists():raise SystemExit('Fixture already prepared; reuse saved identity.')
db=R/'fixture.sqlite'
project='project-regimen-adoption-fixture'
study='study-regimen-adoption-fixture'
shared.admit(db,project)
service=shared.make_service(shared.make_factory(db))
service.create_study_definition(shared.create_command(project_id=project,study_definition_id=study,
    idempotency_key='fixture-study-initial',facts={'picos.population.indication':'合成验收适应症'},reason='创建工程合成验收研究'))
prepared,output=prepared_reference()
opener=_FakeOpener([_FakeResponse(_completion_body(content=json.dumps(output)))])
factory=create_product_regimen_factory(storage_config={'backend':'sqlite','path':str(db)},
    prior_probe_receipt=W/'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',max_input_bytes=2000000,
    credential_resolver=lambda:'synthetic-only',http_opener=opener)
coordinator=factory(project);run=coordinator.start(prepared);state=coordinator.resume(run)
assert state['status']=='ready_for_review' and opener.calls==1
identity={'project_id':project,'study_definition_id':study,'run_id':run,'actor_id':'user:browser-fixture',
          'synthetic_generation_calls':opener.calls,'real_model_calls':0}
(R/'adoption_fixture.json').write_text(json.dumps(identity,indent=2))
(W/'frontend/tests/fixtures/regimen-adoption-fixture.json').write_text(json.dumps(identity,indent=2))
print(json.dumps(identity))
