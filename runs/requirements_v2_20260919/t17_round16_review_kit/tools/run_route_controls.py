from pathlib import Path
from types import SimpleNamespace,ModuleType
import hashlib,json,sys,importlib.util
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'source_excerpts/ai_runtime_fallback_provider.py';data=p.read_bytes()
blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
assert blob=='661f40c430c50b7256c53461eab48d19fa21ac73',blob
class Error(Exception):
    def __init__(self,diagnostics):self.diagnostics=diagnostics
pkg=ModuleType('review_runtime');pkg.__path__=[]
gateway=ModuleType('review_runtime.ai_gateway');gateway.AiProviderRuntimeError=Error
sys.modules[pkg.__name__]=pkg;sys.modules[gateway.__name__]=gateway
spec=importlib.util.spec_from_file_location('review_runtime.ai_runtime_fallback_provider',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Provider:
    def __init__(self,url='http://127.0.0.1:11234/v1',status=None):
        self.provider_name='synthetic';self.model_name='m';self.base_url=url;self.transport_name='openai_compatible';self.expected_response_model='m';self.profile_revision='1';self.default_thinking='enabled';self.default_reasoning_effort='medium';self.status=status;self.calls=0
    def run(self,envelope):
        self.calls+=1
        if self.status: raise Error({'failure_code':'provider_http_error','http_status':self.status})
        return {'ok':True}
rows=[]
a=m.RuntimeFallbackAiProvider([('p',Provider())]);b=m.RuntimeFallbackAiProvider([('p',Provider('http://127.0.0.1:8002/v1'))])
assert a.fallback_chain_id!=b.fallback_chain_id
rows.append({'id':'ROUTE-01','type':'control','expected':'endpoint changes execution identity','passed':True})
p0,p1=Provider(status=429),Provider('http://127.0.0.1:8002/v1');c=m.RuntimeFallbackAiProvider([('p0',p0),('p1',p1)]);c.run({})
assert len(c.attempts)==2 and c.fallback_depth==1 and p0.calls==p1.calls==1
rows.append({'id':'ROUTE-02','type':'control','expected':'429 records both attempts and uses next provider','passed':True})
p0,p1=Provider(status=401),Provider();c=m.RuntimeFallbackAiProvider([('p0',p0),('p1',p1)])
try:c.run({})
except Error:pass
assert p0.calls==1 and p1.calls==0
rows.append({'id':'ROUTE-03','type':'control','expected':'401 does not call fallback','passed':True})
(ROOT/'evidence/route_controls.json').write_text(json.dumps({'source_git_blob':blob,'source_verified':True,'scope':'complete original wrapper; synthetic provider dependencies; no network/model call','tests':rows},indent=2))
print('Original source Git blob verified; 3 route controls passed.')
