"""Bounded actual-product reference extraction; never adopts research facts."""
from pathlib import Path
import sys,json,hashlib
from datetime import datetime,timezone
W=Path(__file__).resolve().parents[3]
for p in (W,W/'services/api'):sys.path.insert(0,str(p))
from app.protocol_workflow.agent1.seed_product import create_product_seed_factory
from app.protocol_workflow.agent1.seed_coordinator import prepare_current_seed
from app.protocol_workflow.agent1.source_identity import SourceIdentityService
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory
R=Path(__file__).resolve().parent
source=Path('/Users/smkzw/Documents/康哲项目资料/模版/方案模版/研究方案库/MG-K10-CSU-001_临床研究方案-V1.3-0212-clean-0211.docx')
content=source.read_bytes()
assert hashlib.sha256(content).hexdigest()=='73024713c28382ca8fca7c9338d7151256b2765d78d512876731156a9a504199'
config={'backend':'sqlite','path':str(R/'reference.sqlite')}
store=LocalArtifactStore(config['path']+'.artifacts')
svc=SourceIdentityService(build_unit_of_work_factory(config),store)
project='project-real-reference-intake-20260913'
adopted=svc.adopt(project_id=project,logical_source_key=source.name,content=content,source_role='company_style_only',source_version='V1.3 (historical reference; not current study authority)',jurisdiction='CN',mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',captured_at=datetime.now(timezone.utc))
brief='本次仅为工程验收中的既有公司方案资料整理。所附MG-K10-CSU-001全文是历史参考资料，不是新项目已确认事实。请从实际正文和表格提取该参考研究的药物、剂型途径、拟用剂量、机制、适应症、期别、人群和对照的候选信息并引用精确原文；如资料不支持则保持缺失，不以推荐填补。本次不创建、不批准任何新研究设计。'
prepared=prepare_current_seed(svc,project,brief,[adopted.current.source.source_artifact_id])
factory=create_product_seed_factory(storage_config=config,prior_probe_receipt=W/'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',max_input_bytes=2000000)
coordinator=factory(project)
# Existing logical run is checked by start; every resumption stays pinned.
run_id=coordinator.start(prepared)
(R/'identity.json').write_text(json.dumps({'project_id':project,'workflow_run_id':run_id,'source_path':str(source),'source_sha256':hashlib.sha256(content).hexdigest(),'input_sha256':prepared.input_sha256,'complete_input_bytes':len(prepared.payload_json.encode()),'model':'glm-5.3-flash','requested_effort':'max','source_scope':'historical_reference_only','canonical_adoption':False},ensure_ascii=False,indent=2))
print(json.dumps({'status':'durably_started','workflow_run_id':run_id,'input_bytes':len(prepared.payload_json.encode())}),flush=True)
try:
    outcome=coordinator.resume(run_id)
except Exception as error:
    (R/'terminal_exception.json').write_text(json.dumps({'type':type(error).__name__,'code':getattr(error,'code',None),'unknown_do_not_redispatch':True}))
    raise SystemExit(2)
(R/'outcome.json').write_text(json.dumps(outcome,ensure_ascii=False,indent=2))
print(json.dumps({'status':outcome['status'],'correction_run_id':outcome['correction_run_id'],'workflow_run_id':run_id}),flush=True)
