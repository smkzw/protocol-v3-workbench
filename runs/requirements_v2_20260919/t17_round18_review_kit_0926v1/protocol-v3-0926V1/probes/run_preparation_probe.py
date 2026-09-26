import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import preparation_create_excerpt as mod

request=SimpleNamespace(stage_size=8, snapshot_id='snapshot_fixture', idempotency_key='fresh_0926_fixture')
probe=mod.PreparationPrefix()
probe._frozen_scope=lambda project,snapshot: (['NCT00000001'],[{'document_id':'protocol1','document_type':'protocol'}])
probe.get=lambda project,batch: {'replayed_batch_id':batch}
probe._idempotent_batch=lambda *args: 'cached_batch_fixture'
rows=[dict(case='P01_existing_replay', result=probe.create('project_fixture',request),outcome='REPLAY_SUCCEEDS')]
probe._idempotent_batch=lambda *args: None
for case in ['P02_current_cache_miss','P03_only_qualifier_fixed']:
    if case=='P03_only_qualifier_fixed':
        # Counterfactual one-line patch applied only to this isolated prefix.
        text=inspect.getsource(mod.PreparationPrefix).replace('_study_facts_hash(journey),','self._study_facts_hash(journey),')
        ns=vars(mod).copy(); exec(text,ns)
        amended=ns['PreparationPrefix']()
        amended._frozen_scope=probe._frozen_scope
        amended._idempotent_batch=probe._idempotent_batch
        amended.get=probe.get
        runner=amended
    else:
        runner=probe
    try:
        result=runner.create('project_fixture',request)
        rows.append(dict(case=case,outcome='NO_ERROR',result=result))
    except Exception as exc:
        rows.append(dict(case=case,outcome='REPRODUCED_ERROR',error_type=type(exc).__name__,message=str(exc)))
result=dict(kind='source-derived prefix with mock dependencies, not full repository tests',cases=rows)
p=Path(__file__).resolve().parents[1]/'evidence'/'preparation_probe_results.json'
p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
