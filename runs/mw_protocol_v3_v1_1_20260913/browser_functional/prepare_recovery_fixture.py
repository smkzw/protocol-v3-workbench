"""Add only a second synthetic study; reuse the previously generated design."""
from pathlib import Path
import sys,json
W=Path(__file__).resolve().parents[3]
for p in (W,W/'services/api',W/'tests/protocol_v3/integration'):sys.path.insert(0,str(p))
import integration_shared as shared
R=Path(__file__).resolve().parent
identity=json.loads((R/'adoption_fixture.json').read_text())
identity['study_definition_id']='study-regimen-recovery-fixture'
shared.make_service(shared.make_factory(R/'fixture.sqlite')).create_study_definition(shared.create_command(
    project_id=identity['project_id'],study_definition_id=identity['study_definition_id'],
    idempotency_key='fixture-recovery-study-initial',facts={'picos.population.indication':'合成恢复验收适应症'},
    reason='创建仅用于丢失确认回执的工程实例'))
identity['new_model_calls']=0
(R/'recovery_fixture.json').write_text(json.dumps(identity,indent=2))
(W/'frontend/tests/fixtures/regimen-recovery-fixture.json').write_text(json.dumps(identity,indent=2))
print(json.dumps(identity))
