"""Real product API/SQLite and React inspection; synthetic model transport only."""
from pathlib import Path
import sys, json, socket, os
W = Path(__file__).resolve().parents[3]
for p in (W, W/'services/api', W/'tests/protocol_v3', W/'tests/protocol_v3/integration'): sys.path.insert(0,str(p))
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn
from app.protocol_workflow.api.composition import ProtocolWorkflowMountConfig, mount_protocol_workflow_router
from app.protocol_workflow.agent1.seed_product import create_product_seed_factory
from app.protocol_workflow.agent2.product import create_product_regimen_factory
import io
class _FakeResponse(io.BytesIO):
    status=200
    def __init__(self,payload): super().__init__(json.dumps(payload).encode())
    def getcode(self): return 200
def _completion_body(content,response_id):
    return {'id':response_id,'model':'glm-5.3-flash','choices':[{'index':0,'message':{'role':'assistant','content':content},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1}}
from integration_shared import admit
R=Path(__file__).resolve().parent
PROJECT='project-intake-browser-fixture'
db=R/'fixture.sqlite'
admit(db,PROJECT)
class SyntheticTransport:
    def __init__(self):
        self.calls=json.loads((R/'transport_count.json').read_text()).get('synthetic_generation_calls',0) if (R/'transport_count.json').exists() else 0
    def open(self, request, timeout=None):
        self.calls+=1
        (R/'transport_count.json').write_text(json.dumps({'synthetic_generation_calls':self.calls,'real_model_calls':0}))
        return _FakeResponse(_completion_body(content='{"fields":{}}',response_id='browser-fixture-'+str(self.calls)))
factory=create_product_seed_factory(storage_config={'backend':'sqlite','path':str(db)},prior_probe_receipt=W/'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',max_input_bytes=2000000,credential_resolver=lambda:'synthetic-fixture-only',http_opener=SyntheticTransport())
class NoProviderTransport:
    def open(self,*args,**kwargs):raise RuntimeError('This fixture only reads previously saved designs; provider calls are disabled.')
designs=create_product_regimen_factory(storage_config={'backend':'sqlite','path':str(db)},prior_probe_receipt=W/'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',max_input_bytes=2000000,credential_resolver=lambda:'synthetic-fixture-only',http_opener=NoProviderTransport())
app=FastAPI()
@app.middleware('http')
async def lose_one_synthetic_adoption_receipt(request,call_next):
    target=request.method=='POST' and request.url.path.endswith('/adopt')
    body=await request.json() if target else {}
    response=await call_next(request)
    marker=R/'recovery_reply_intercepted.json'
    if target and body.get('study_definition_id')=='study-regimen-recovery-fixture' and response.status_code==200 and not marker.exists():
        marker.write_text(json.dumps({'scenario':'synthetic after-commit reply interruption','operation_id':body.get('operation_id'),'original_status':200}))
        return JSONResponse({'detail':{'message':'本次保存回执连接中断，原操作记录已保留。'}},status_code=503)
    return response
mount_protocol_workflow_router(app,ProtocolWorkflowMountConfig(enabled=True,db_path=db),seed_coordinator_factory=factory,regimen_coordinator_factory=designs)
sock=socket.socket(); sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
sock.bind(('127.0.0.1',int(os.environ.get('FIXTURE_API_PORT','0')))); sock.listen(128)
port=sock.getsockname()[1]
(R/'server.json').write_text(json.dumps({'api_url':f'http://127.0.0.1:{port}','project_id':PROJECT,'db_path':str(db),'transport':'synthetic fixture; no provider calls'},ensure_ascii=False,indent=2))
uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='info')).run(sockets=[sock])
