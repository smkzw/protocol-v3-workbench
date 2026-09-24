"""Run an unmodified source method excerpt with temporary real SQLite rows.
Not the full application, not a real provider call, not a crash-recovery E2E.
"""
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime,timezone
import json,sqlite3,time,tempfile
ROOT=Path(__file__).resolve().parents[1]
class Conflict(ValueError): pass
@dataclass
class Acquisition:
    logical_call_id: str|None=None
    replay: object=None
ns=dict(json=json,time=time,datetime=datetime,timezone=timezone,
        MedicalWritingAuthoringJourneyConflictError=Conflict,
        _GenerationReservationAcquisition=Acquisition,
        _WAITER_DEADLINE_FLIP_NOTE='in-flight reservation observed beyond the wait bound; owner presumed interrupted/restarted')
exec(compile((ROOT/'source_excerpts/acquire_generation_reservation.py').read_text(), 'acquire_generation_reservation.py','exec'), ns)
class Harness:
    _generation_reservation_wait_seconds=0.0  # deterministic injected observation budget
    acquire=ns['_acquire_generation_reservation']
    def __init__(self,path,status='in_flight',updated='2000-01-01T00:00:00Z',attempts=1):
        self.path=path;self.superseded=0
        with self._connect() as c:
            c.execute('CREATE TABLE medical_writing_authoring_journey_generation_reservations(project_id TEXT,expected_revision INTEGER,operation TEXT,logical_call_id TEXT,transport_attempt_count INTEGER,status TEXT,event_id TEXT,failure_note TEXT,updated_at TEXT,attempt_history TEXT)')
            c.execute('INSERT INTO medical_writing_authoring_journey_generation_reservations VALUES(?,?,?,?,?,?,?,?,?,?)',('p',4,'prefill_generate','old-call',attempts,status,None,None,updated,'[]'))
    def _connect(self):
        c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;return c
    def _read_generation_reservation(self,p,r,o):
        with self._connect() as c:return c.execute('SELECT * FROM medical_writing_authoring_journey_generation_reservations WHERE project_id=? AND expected_revision=? AND operation=?',(p,r,o)).fetchone()
    def _replay_completed_reservation(self,*args): return Acquisition(replay='recorded-result')
    def _try_insert_generation_reservation(self,*args):raise AssertionError('unneeded path')
    def _supersede_generation_reservation(self,p,r,o,**kwargs):
        # Stub dependency, called only by control tests. Not production supersede implementation.
        self.superseded+=1
        with self._connect() as c:c.execute("UPDATE medical_writing_authoring_journey_generation_reservations SET status='in_flight',logical_call_id='new-call' WHERE logical_call_id=?",(kwargs['previous_call_id'],))
        return 'new-call'
    def run(self,force):
        err='';result=None
        try:result=self.acquire(project_id='p',expected_revision=4,operation='prefill_generate',force=force,enricher_timeout_seconds=900)
        except Conflict as e:err=str(e)
        row=dict(self._read_generation_reservation('p',4,'prefill_generate'))
        return dict(error=err,status=row['status'],logical_call_id=row['logical_call_id'],history_count=len(json.loads(row['attempt_history'])),superseded=self.superseded,result=None if result is None else result.__dict__)
rows=[]
with tempfile.TemporaryDirectory() as td:
    h=Harness(Path(td)/'old.db')
    a=h.run(True); b=h.run(True)
    assert a['status']==b['status']=='in_flight' and not b['superseded'] and 'force cannot interrupt' in b['error']
    rows.append(dict(id='PREFILL-01',kind='reproduced',case='ancient in_flight repeatedly forced',observed=b))
    c=h.run(False)
    assert c['status']=='unknown_outcome' and c['history_count']==1
    rows.append(dict(id='PREFILL-02',kind='control',case='non-force reaches existing wait deadline branch',observed=c))
    d=h.run(True)
    assert d['result']['logical_call_id']=='new-call' and d['superseded']==1
    rows.append(dict(id='PREFILL-03',kind='control',case='explicit force after unknown can enter supersede helper',observed=d))
    h=Harness(Path(td)/'live.db',updated=datetime.now(timezone.utc).isoformat())
    c=h.run(True); assert c['status']=='in_flight' and not c['superseded']
    rows.append(dict(id='PREFILL-04',kind='control',case='live force is not allowed to seize owner',observed=c))
    h=Harness(Path(td)/'done.db',status='completed');c=h.run(True)
    assert c['result']['replay']=='recorded-result'
    rows.append(dict(id='PREFILL-05',kind='control',case='completed result replays',observed=c))
(ROOT/'evidence/reservation_probes.json').write_text(json.dumps({'scope':'one original method with temporary SQLite, injected wait budget and helper stubs','tests':rows},ensure_ascii=False,indent=2))
print('5 scenario assertions passed (1 reproduces a defect; 4 are controls).')
