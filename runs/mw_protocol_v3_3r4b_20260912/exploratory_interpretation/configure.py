import json
from pathlib import Path
from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog,build_direct_fact_catalog
from app.protocol_workflow.registries.chapters import load_chapter_registry,lint_registry
from scripts.qc.protocol_v3.assemble_chapter_registry import assemble_registries
from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
b=Path('config/medical_writing/protocol_v3/templates/tp_ma_07_v2');out=Path('runs/mw_protocol_v3_3r4b_20260912/exploratory_interpretation');claim='exploratory_non_confirmatory'
p=b/'chapter_contracts/v2_n_3_4_2.json';raw=json.loads(p.read_text());old=raw['conditional_applicability_rules'];(out/'retired_rules.json').write_text(json.dumps(old,ensure_ascii=False,indent=2)+'\n');raw['contract_version']=raw['chapter_skill_version']='3.4.0';raw['conditional_applicability_rules']=[]
x=next(x for x in raw['substantive_content']['claim_requirements'] if x['claim_type']==claim);x.update(obligation='required',qualifying_conditions=[],rationale='探索性分析明确解释范围，不以探索性结果直接宣称确证性有效；可恰当作描述/支持，拟改变分析意图应返回假设家族与多重性方案重新确认，而非靠非空处置文字激活。')
raw['substantive_content']['evidence_source_requirements'].append(dict(source_roles=['project_primary'],admission_claim_types=[claim],allowed_locator_kinds=['body','table'],require_context_window=True,minimum_quality_score=0.9))
c=ChapterContractV2.model_validate_json(json.dumps(raw));p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
p=b/'chapter_skills/v2_n_3_4_2.json';raw=json.loads(p.read_text());raw['skill_version']='3.4.0';raw['prompt_contract']['instructions']='按探索性终点合同给出终点、处置和分析意图，并明确解释范围。探索性分析不得直接表述为确证性有效；恰当的描述性/支持性分析可以保留，不能把其归为禁止内容。若拟转为确证性分析，回到假设家族、多重性计划及人审确认，不在本章自动升级。未开展时明确处置，不虚构终点。';p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
p=b/'applicability_rules.json';raw=json.loads(p.read_text());rid=old[0]['conditional_applicability_rule_id'];assert rid in raw['pending_rule_ids'];raw['pending_rule_ids'].remove(rid);p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
p=Path('tests/fixtures/protocol_v3/chapter_content_v2/batch2.json');raw=json.loads(p.read_text())
for f in raw['fixtures']:
 if f['chapter_contract_id']==c.chapter_contract_id and f['fixture_kind']=='positive':
  if not any(x['claim_type']==claim for x in f['content']['claims']):f['content']['claims'].append({'claim_type':claim,'statement':'Synthetic exploratory interpretation only, not confirmatory efficacy'})
  f['content']['evidence'].append({'source_role':'project_primary','admission_claim_type':claim,'locator_kind':'body','locator':'synthetic:analysis-intent:1','context':'Synthetic agreed exploratory interpretation scope','quality_score':0.95})
p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
reg=load_chapter_registry(assemble_registries(b/'chapter_contracts',b/'chapter_skills',[Path(f'tests/fixtures/protocol_v3/chapter_content_v2/batch{i}.json') for i in range(1,9)]));p=b/'fact_bindings.json';old=FactBindingCatalog.model_validate_json(p.read_text());p.write_text(build_direct_fact_catalog(reg,declarations=old.bindings).model_dump_json(indent=2)+'\n');report=lint_registry(b,reg,require_complete=True);(out/'lint.json').write_text(report.model_dump_json(indent=2)+'\n');print(report.status,len(report.findings))
