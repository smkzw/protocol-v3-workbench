import json
from pathlib import Path
from app.protocol_workflow.registries.applicability import ApplicabilityRuleCatalog
from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog,build_direct_fact_catalog
from app.protocol_workflow.registries.chapters import load_chapter_registry,lint_registry
from scripts.qc.protocol_v3.assemble_chapter_registry import assemble_registries
from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
b=Path('config/medical_writing/protocol_v3/templates/tp_ma_07_v2');out=Path('runs/mw_protocol_v3_3r4b_20260912/followup_recording_plan');key='procedure.unscheduled_contact_recording_plan';members=['date_recording','modality_recording','reason_recording','assessment_rules','safety_information_handling']
p=b/'chapter_contracts/v2_n_7_3.json';raw=json.loads(p.read_text());old=raw['conditional_applicability_rules'];legacy=old[0]['required_when_active_fact_paths'];(out/'retired_rules.json').write_text(json.dumps(old,ensure_ascii=False,indent=2)+'\n');raw['contract_version']=raw['chapter_skill_version']='3.4.0';raw['conditional_applicability_rules']=[]
raw['substantive_content']['fact_requirements'].append(dict(fact_path=key,obligation='required',rationale='body-child492要求未来如发生计划外访视（含电话随访）的记录规则：日期、方式、原因、评估内容及安全性信息处理；结构化规则不是实际发生日期或访视结果。'))
raw['substantive_content']['fact_requirements'] += [dict(fact_path=x,obligation='optional',rationale='历史执行记录路径保留追溯；不得从实际访视记录推定方案规则，不再绑定为当前方案生成输入。') for x in legacy]
c=ChapterContractV2.model_validate_json(json.dumps(raw));p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
p=b/'chapter_skills/v2_n_7_3.json';raw=json.loads(p.read_text());raw['skill_version']='3.4.0';raw['prompt_contract']['instructions']+=' 必须依据unscheduled_contact_recording_plan写出如发生计划外/电话访视时如何记录日期、方式、原因、评估及安全性信息；没有实际访视也应写出此规则。不索要未来访视日期，不虚构记录，不把历史contact_visit字段复制成方案计划。';p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
p=b/'applicability_rules.json';raw=json.loads(p.read_text());rid=old[0]['conditional_applicability_rule_id'];assert rid in raw['pending_rule_ids'];raw['pending_rule_ids'].remove(rid);s=json.dumps(raw,ensure_ascii=False,indent=2)+'\n';ApplicabilityRuleCatalog.model_validate_json(s);p.write_text(s)
p=Path('tests/fixtures/protocol_v3/chapter_content_v2/batch4.json');raw=json.loads(p.read_text());raw['fact_vocabulary']=sorted(set(raw['fact_vocabulary'])|{key})
# Add the new required plan to positive synthetic input only. All existing
# negative fixtures and expected values remain byte-equivalent as JSON values.
for f in raw['fixtures']:
 if f['chapter_contract_id']==c.chapter_contract_id and f['fixture_kind']=='positive':
  f['content']['facts'].append({'fact_path':key,'value':{k:'Synthetic future recording rule, not an actual visit' for k in members}})
p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
reg=load_chapter_registry(assemble_registries(b/'chapter_contracts',b/'chapter_skills',[Path(f'tests/fixtures/protocol_v3/chapter_content_v2/batch{i}.json') for i in range(1,9)]));p=b/'fact_bindings.json';old=FactBindingCatalog.model_validate_json(p.read_text());cat=build_direct_fact_catalog(reg,declarations=old.bindings)
cat=cat.model_copy(update={'bindings':tuple(x.model_copy(update={'canonical_path':None}) if x.fact_path in legacy else x.model_copy(update={'value_type':'object','required_members':{k:'string' for k in members}}) if x.fact_path==key else x for x in cat.bindings)})
p.write_text(cat.model_dump_json(indent=2)+'\n');report=lint_registry(b,reg,require_complete=True);(out/'lint.json').write_text(report.model_dump_json(indent=2)+'\n');print(report.status,len(report.findings))
