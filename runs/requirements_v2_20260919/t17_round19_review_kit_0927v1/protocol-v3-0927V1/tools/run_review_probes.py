#!/usr/bin/env python3
"""Offline observations against captured source excerpts, not product tests.
No network/model/server/production DB calls are made. Subprocess responses are fakes.
"""
from __future__ import annotations
import hashlib, importlib.util, json, os, sys, tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m
G = load('gate_excerpt', ROOT/'source_excerpts/gate_methods.py')
M = load('model_excerpt', ROOT/'source_excerpts/model_phase_scheduler.py')
observations=[]
def observe(identifier, title, expected, observed, mode, agrees):
    observations.append(dict(id=identifier, title=title, expected=expected,
                             observed=observed, mode=mode, agrees=bool(agrees)))
def report(cases=None, *, rc=0, failures=None, skipped=None):
    cases = ['tests/test_demo.py::test_ok'] if cases is None else cases
    return dict(ok=True,total=len(cases), cases=cases, failures=failures or [],
                errors=[], skipped=skipped or [], returncode=rc)
def ev(r, required=(), baseline=None, head='new'):
    why=[]
    v=G.evaluate_report_against_baseline(r, baseline, head, list(required), False, why)
    return {**v, 'reasons':why}

r=ev(report())
observe('P01','ordinary successful report', 'PASS',r['verdict'],'control',r['verdict']=='PASS')
f=dict(nodeid='tests/test_demo.py::test_bad', fingerprint='fp',message='bad')
r=ev(report([f['nodeid']],rc=1,failures=[f]))
observe('P02','unknown failing test','FAIL',r['verdict'],'control',r['verdict']=='FAIL')
r=ev(report(rc=2))
observe('P03','collection exit at helper level','FAIL',r['verdict'],'control',r['verdict']=='FAIL')
req='tests/test_demo.py::test_required'
r=ev(report([req],skipped=[req]),[req])
observe('P04','required node exists but was skipped','FAIL',r['verdict'],'counterexample',r['verdict']=='FAIL')
r=ev(report(['tests/test_demo.py::ClassB::test_required']), ['tests/test_demo.py::ClassA::test_required'])
observe('P05','wrong class has the same test leaf','FAIL',r['verdict'],'counterexample',r['verdict']=='FAIL')
r=ev(report(['tests/test_demo.py::test_required[ok]']), ['tests/test_demo.py::test_required[bad]'])
observe('P06','specific required parameter never ran','FAIL',r['verdict'],'counterexample',r['verdict']=='FAIL')
r=ev(report([]))
observe('P07','contradictory empty parsed report with rc0','FAIL',r['verdict'],'malformed-input',r['verdict']=='FAIL')
for code,label in [(None,'missing report'),(2,'collection error')]:
    inp= dict(ok=False,reason='report_missing',returncode=None) if code is None else report(rc=2)
    out=ev(inp)
    # Exact cmd_run projection fields from the upstream excerpt (lines 552-558).
    try:
        projected={k:out[k] for k in ('ran','failed_ids','known_matched','dissolved',
             'suspected_data_class','suspected_fingerprint_drift',
             'missing_required_nodes','baseline_not_run_count')}
        observed='structured verdict returned'
    except KeyError as exc:
        observed=f'KeyError:{exc.args[0]}'
    observe('P08' if code is None else 'P09',label+' through cmd_run projection',
            'structured verdict returned',observed,'helper+consumer excerpt',observed=='structured verdict returned')

baseline={'baseline_sha':'old','pytest_failures':[f]}
r=ev(report([f['nodeid']],rc=1,failures=[f]),baseline=baseline,head='old')
observe('P10','same-HEAD known failure control','PASS_WITH_KNOWN_FAILURES',r['verdict'],'control',r['verdict']=='PASS_WITH_KNOWN_FAILURES')
# Upstream cmd_run checks this exact mismatch before running the suite.
head='new'
blocked=bool(baseline and head and baseline.get('format')!='UNREADABLE' and baseline.get('baseline_sha')!=head)
observe('P11','unchanged failure baseline after next commit','permit explicit ancestor-base comparison',
        'BLOCKED before pytest' if blocked else 'allowed','policy counterexample',not blocked)

with tempfile.TemporaryDirectory(prefix='review0927_') as td:
    root=Path(td)
    (root/'services/api/app').mkdir(parents=True)
    lintbin=root/'frontend/node_modules/.bin/eslint';lintbin.parent.mkdir(parents=True);lintbin.write_text('fixture')
    with patch.object(G.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='',stderr='No module named pyflakes')):
        result=G.run_pyflakes(root)
    observe('P12','pyflakes unavailable inside Python','ok=False',result,'mock subprocess',not result['ok'])
    for ident,out in [('P13',''),('P14','not JSON')]:
        with patch.object(G.subprocess,'run',return_value=SimpleNamespace(returncode=2,stdout=out,stderr='Configuration error')):
            result=G.run_eslint(root)
        observe(ident,'eslint execution/report failure','ok=False',result,'mock subprocess',not result['ok'])
    captured={}
    def fake_run(*a,**kw):
        captured.update(kw)
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    with patch.dict(os.environ,{'WORKBENCH_RUNTIME_DIR':'/fixture/live-must-not-use','HTTP_PROXY':'http://fixture-proxy.invalid'}), patch.object(G.subprocess,'run',side_effect=fake_run):
        G.run_pytest(root,root/'r.xml',1,['tests'])
    inherited = captured['env'].get('WORKBENCH_RUNTIME_DIR')=='/fixture/live-must-not-use'
    observe('P15','offline test inherits live runtime env','not inherited',{'live_runtime_inherited':inherited,'proxy_inherited':'HTTP_PROXY' in captured['env']},'mock subprocess',not inherited)
    for d in ('aaa-wrong','zzz-intended'):
        p=root/d/'tools/acceptance/required_nodes.json';p.parent.mkdir(parents=True);p.write_text('[]')
    chosen=G.discover_repo_root(root)
    observe('P16','multiple repos under supplied parent','fail ambiguity',chosen.name,'temporary filesystem',False)

calls=[]
with patch.object(M,'warm_translation_model',side_effect=lambda: (calls.append('translation') or (True,''))),patch.object(M,'warm_triage_model',side_effect=lambda:(calls.append('triage') or (True,''))):
    M.phase_model_readiness('translation')
observe('P17','translation readiness invokes both warm-ups',['translation'],calls,'mock models',calls==['translation'])
class Response:
    status=200
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self):raise AssertionError('response body should be inspected')
with patch.object(M.urllib.request,'urlopen',return_value=Response()):
    result=M._chat_probe('http://fixture.invalid/v1','expected-model')
observe('P18','HTTP200 with unexamined identity/body','must not prove model readiness',result,'mock HTTP',not result[0])

b=(ROOT/'source_excerpts/model_phase_scheduler.py').read_bytes()
blob=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
result={'scope':'isolated source excerpts + mocks, no full product run',
        'upstream_commit':'5b4c8c11692fc3118eb21bfe80877f5ce9d76c65',
        'model_module_git_blob':blob,
        'model_module_git_blob_matches':blob=='960ea817505d54751472d4969240d1442ba36e32',
        'observations':observations,
        'count':len(observations),'agree_count':sum(x['agrees'] for x in observations),
        'disagree_count':sum(not x['agrees'] for x in observations)}
path=ROOT/'evidence/review_probe_results.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps({k:result[k] for k in ('count','agree_count','disagree_count','model_module_git_blob_matches')},ensure_ascii=False))
for x in observations: print(x['id'],x['mode'],repr(x['observed']))
