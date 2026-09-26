"""Read-only synthetic counterexamples, not full product tests."""
import json
from pathlib import Path
from numeric_gate_excerpt import numeric_subcheck

CASES = [
    ('N01', 'Dose 5 mg.', '剂量50 mg。', ['5'], ['50'], True),
    ('N02', 'Dose 1.5 mg.', '剂量15 mg。', ['1.5'], ['15'], True),
    ('N03', 'Enroll 120 participants.', '入组1200例受试者。', ['120'], ['1200'], True),
    ('N04', 'Evaluate at week 12.', '在第120周评估。', ['12'], ['120'], True),
    ('N05', '116 million people.', '1.16亿人。', ['116'], ['1.16'], False),
    ('N06', '116 million people.', '1.16万人。', ['116'], ['1.16'], True),
    ('N07', '635 billion dollars.', '6350亿美元。', ['635'], ['6350'], False),
    ('N08', '116 million people.', '2.50亿人。', ['116'], ['2.5'], True),
    ('N09', 'Dose 5 mg.', '剂量7 mg。', ['5'], ['7'], True),
    ('N10', '2 visits and 2 calls.', '2次访视及联系。', ['2', '2'], ['2'], True),
    ('N11', 'Dose 15 mg.', '剂量1.5 mg。', ['15'], ['1.5'], True),
    ('N12', 'Dose 5 mg.', '剂量5 mg。', ['5'], ['5'], False),
]
rows=[]
for cid, src, tgt, sn, tn, expected in CASES:
    observed=numeric_subcheck(src,tgt,sn,tn)
    rows.append(dict(id=cid,source=src,translation=tgt,source_tokens=sn,target_tokens=tn,
                     expected_numeric_drift=expected,observed_numeric_drift=observed,
                     outcome='MATCH' if expected==observed else 'COUNTEREXAMPLE'))
result=dict(kind='isolated source-derived numeric subcheck, not end-to-end',
            source_commit='53feb06fc1402df820a6dba5d8b6e3fa15d50437',
            total=len(rows),counterexamples=sum(x['outcome']=='COUNTEREXAMPLE' for x in rows),cases=rows)
out=Path(__file__).resolve().parents[1]/'evidence'/'numeric_probe_results.json'
out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
