"""Offline branch probes using source-derived excerpts and synthetic objects.
Not full application tests, no network, no PDF parsing, no production mutation.
"""
from pathlib import Path
from types import SimpleNamespace as NS
import sys, json
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'source_excerpts'))
from download_boundaries import ScopeExcerpt, DownloadPrefix

def doc(kind, did):
    return NS(document_type=kind, document_id=did, filename=did+'.pdf',
              document_date='2024-01-01', upload_date='2025-01-01', declared_size=1,
              download_url='https://clinicaltrials.gov/synthetic/'+did+'.pdf')

def fixture(n=1, kinds=('protocol','sap','other','protocol_sap')):
    candidates=[NS(nct_id=f'NCT{i:08d}', public_documents=[doc(k,f'd{i}_{j}') for j,k in enumerate(kinds)])
                for i in range(1,n+1)]
    ids=[x.nct_id for x in candidates]
    decisions=[NS(nct_id=x, relevance_status='direct_competitor') for x in ids]
    snapshot=NS(candidates=candidates)
    journey=NS(corpus_triage=NS(status='finalized', snapshot_id='s', retained_candidate_ids=ids),
               discovery_basket_projection=None, search_plan=NS(latest_snapshot_id='s'))
    repo=NS(search_snapshot=lambda *_:snapshot, relevance_decisions_for_snapshot=lambda *_:decisions,
            relevance_decision=lambda *_:decisions[0])
    def absent(*_): raise KeyError('absent')
    repo.document_artifact=absent
    obj=ScopeExcerpt(); obj.repository=repo; obj.journey_service=NS(get=lambda *_:journey)
    return obj, repo, snapshot, journey

results=[]
def record(name, expected, actual, kind):
    results.append(dict(name=name, check_kind=kind, expected=expected, actual=actual,
                        expectation_met=expected==actual))

obj,repo,ss,j=fixture()
ids,entries=obj._frozen_scope('p','s')
record('batch already excludes standalone SAP and other/ICF', ['protocol','protocol_sap'],
       sorted(x['document_type'] for x in entries), 'existing_control')
obj,repo,ss,j=fixture(60,('protocol',))
ids,entries=obj._frozen_scope('p','s')
record('new study budget not implemented at frozen_scope',30,len(ids),'new_requirement_gap')
obj,repo,ss,j=fixture(1,('protocol','protocol','protocol_sap'))
ids,entries=obj._frozen_scope('p','s')
record('new canonical-document selection absent',1,len(entries),'new_requirement_gap')
obj,repo,ss,j=fixture(7,('protocol',))
record('small set remains seven',7,len(obj._frozen_scope('p','s')[0]),'existing_control')
class ReachedDownload(Exception): pass
for kind in ('protocol','sap','other'):
    obj,repo,ss,j=fixture(1,(kind,))
    target=DownloadPrefix(); target.repository=repo
    calls=[]; events=[]
    def intercept(url, **kwargs):
        calls.append(url); raise ReachedDownload()
    target.client=NS(fetch_binary=intercept)
    request=NS(snapshot_id='s', nct_id=ss.candidates[0].nct_id, document_id='d1_0')
    try: target.ingest('p',request,progress_callback=events.append)
    except ReachedDownload: pass
    record('generic ingest download attempt for '+kind, kind=='protocol',bool(calls),
           'existing_control' if kind=='protocol' else 'missing_service_boundary')
    if kind=='sap':
        record('generic SAP download receives protocol display label',True,
               bool(events and 'Protocol' in events[0]['current_substep']),'observed_mislabel')
# Counts from handoff; not independently fetched runtime data.
summary={'basis':'source-derived excerpts; synthetic mocks; comments/type annotations/whitespace abbreviated',
         'source_commit':'ee12adc88a8110c2443393ac7b4134356053c684',
         'not_run':['full backend','real user database','browser','model generation','Word','live downloads'],
         'checks':results,
         'check_count':len(results),
         'reported_translation_counts':{'candidate_ready':38,'fidelity_blocked':164,'failed':26,'total':228},
         'reported_translation_shares_pct':{'candidate_ready':round(38/228*100,1),
                                            'fidelity_blocked':round(164/228*100,1),
                                            'failed':round(26/228*100,1)}}
path=ROOT/'evidence/scope_probe_results.json'; path.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
