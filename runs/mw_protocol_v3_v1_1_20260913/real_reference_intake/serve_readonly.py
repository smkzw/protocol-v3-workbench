"""Read-only actual-product result viewer, isolated engineering database."""
from pathlib import Path
import sys,json,socket,os
W=Path(__file__).resolve().parents[3]
for p in (W,W/'services/api'):sys.path.insert(0,str(p))
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn
from app.protocol_workflow.api.composition import ProtocolWorkflowMountConfig,mount_protocol_workflow_router
from app.protocol_workflow.storage.sqlite import admit_project
R=Path(__file__).resolve().parent
i=json.loads((R/'identity.json').read_text());db=R/'reference.sqlite'
admit_project({'backend':'sqlite','path':str(db)},i['project_id'],admitted_at='2026-09-13T05:10:00+00:00')
app=FastAPI()
@app.middleware('http')
async def artifact_view_only(request,call_next):
    if request.method not in {'GET','HEAD'}:return JSONResponse({'detail':{'message':'此页仅查看已保存的验收结果，不发起生成。'}},status_code=405)
    return await call_next(request)
mount_protocol_workflow_router(app,ProtocolWorkflowMountConfig(enabled=True,db_path=db))
sock=socket.socket();sock.bind(('127.0.0.1',int(os.environ.get('REFERENCE_VIEW_PORT','0'))));sock.listen(128);port=sock.getsockname()[1]
(R/'viewer_server.json').write_text(json.dumps({'api_url':f'http://127.0.0.1:{port}','project_id':i['project_id'],'workflow_run_id':i['workflow_run_id'],'mode':'readonly_actual_result'},indent=2))
uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='info')).run(sockets=[sock])
