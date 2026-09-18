"""Bound verification for A; unfinished B red tests explicitly outside this run."""
from pathlib import Path
import subprocess, json, hashlib, datetime
root=Path.cwd();r=root/'runs/mw_protocol_v3_3r4a_20260912'
paths=['packages/contracts/workbench_contracts/protocol_v3.py','services/api/app/protocol_workflow/registries/chapters.py','services/api/app/protocol_workflow/registries/fact_bindings.py','tests/protocol_v3/test_chapter_fact_binding.py','config/medical_writing/protocol_v3/templates/tp_ma_07_v2/fact_bindings.json']
def hashes():return {p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}
env={'PATH':'/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin','HOME':'/Users/smkzw','TMPDIR':subprocess.check_output(['/usr/bin/getconf','DARWIN_USER_TEMP_DIR'],text=True).strip(),'LANG':'en_US.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','PYTHONPATH':'tests/protocol_v3:services/api:packages:.'}
cmd=[str(root/'runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python'),'-m','pytest','tests/protocol_v3','--ignore=tests/protocol_v3/test_chapter_applicability.py','-q',f'--junitxml={r}/review_verification.xml']
record={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cwd':str(root),'command':cmd,'env':env,'before':hashes(),'scope_exclusion':'15 B predicate tests are intentionally red, module not implemented; not claimed green or accepted'}
with (r/'review_verification.log').open('w') as f:result=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT)
record.update({'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'returncode':result.returncode,'after':hashes()})
(r/'review_verification_receipt.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
print(json.dumps({'returncode':result.returncode,'source_unchanged':record['before']==record['after']}))
raise SystemExit(result.returncode)
