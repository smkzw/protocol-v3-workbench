#!/usr/bin/env python3
"""Read-only JUnit timing/failure-family summary. Not an acceptance gate.
Case-time sum is not wall-clock latency, especially under parallel execution.
Native pytest node IDs are used only when explicitly recorded as properties;
classname+name is a diagnostic key, never proof that a mandatory node ran.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

class ReportError(ValueError):
    pass

def analyze(path: Path, top: int = 20) -> dict:
    if top < 1:
        raise ReportError('top must be positive')
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ReportError(f'unreadable JUnit: {type(exc).__name__}') from exc
    if root.tag not in {'testsuite', 'testsuites'}:
        raise ReportError('unsupported XML root')
    cases=[]
    families=Counter()
    diagnostic_ids=Counter()
    for node in root.iter('testcase'):
        try:
            duration=float(node.get('time','0'))
        except ValueError as exc:
            raise ReportError('invalid case duration') from exc
        if not math.isfinite(duration) or duration < 0:
            raise ReportError('duration must be nonnegative and finite')
        classname=node.get('classname','')
        name=node.get('name','')
        key=f'{classname}::{name}'
        diagnostic_ids[key]+=1
        props={p.get('name'):p.get('value') for p in node.findall('./properties/property')}
        native_id=props.get('pytest_nodeid')
        status='passed'
        # Infrastructure errors take precedence over test failure/skips.
        if node.find('error') is not None:status='error'
        elif node.find('failure') is not None:status='failed'
        elif node.find('skipped') is not None:status='skipped'
        bad=node.find('error')
        if bad is None:bad=node.find('failure')
        if bad is not None:
            families[(classname, bad.get('type','unspecified'))]+=1
        cases.append({'diagnostic_id':key,'native_nodeid':native_id,
                      'status':status,'case_seconds':duration})
    if not cases:
        raise ReportError('no testcase records; cannot infer a successful run')
    counts=dict(Counter(c['status'] for c in cases))
    duplicates=sorted(k for k,n in diagnostic_ids.items() if n>1)
    return {
        'schema':'junit-diagnostic-profile/v1','source':str(path),
        'purpose':'diagnostic only; raw process exit and exact node manifest required for gating',
        'case_records':len(cases),'counts':counts,
        'case_time_sum_seconds':round(sum(c['case_seconds'] for c in cases),6),
        'wall_clock_seconds':None,
        'native_nodeid_missing_records':sum(c['native_nodeid'] is None for c in cases),
        'duplicate_diagnostic_ids':duplicates,
        'slowest_case_records':sorted(cases,key=lambda c:c['case_seconds'],reverse=True)[:top],
        'failure_families':[{'classname':k[0],'error_type':k[1],'records':v}
                            for k,v in families.most_common()],
    }

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('report',type=Path);p.add_argument('--top',type=int,default=20)
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    try:data=analyze(a.report,a.top)
    except ReportError as exc:
        print(json.dumps({'status':'INVALID_REPORT','reason':str(exc)}),file=sys.stderr)
        return 2
    text=json.dumps(data,ensure_ascii=False,indent=2)+'\n'
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(text,encoding='utf-8')
    else:print(text,end='')
    return 0
if __name__=='__main__':raise SystemExit(main())
