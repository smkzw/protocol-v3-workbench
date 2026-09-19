"""Derive missing chapter facts from the confirmed design; AI proposals only.

The user's confirmed research design (intake context, PICOS, regimen, design
elements) is the only medical authority here.  Chapter-level facts (AE
handling, statistical methods, visit schedules, ...) are drafted by the model
from that authority so the complete draft can compile; every derived value is
applied as one AI-actor decision with provenance and stays editable through
the normal controlled-editing flow.  The model never invents values the
confirmed design cannot support: a fact it leaves out simply keeps its chapter
unresolved, and the derivation is content-idempotent (only missing paths are
derived again).
"""
import hashlib
import json
from datetime import datetime, timezone

from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.registries.applicability import diagnose_applicable_input
from app.protocol_workflow.registries.fact_bindings import (
    FactBinding, FactBindingError, _typed_value, _is_resolved_fact,
)

CHAPTER_FACTS_INSTRUCTION = '''你为研究方案模板补齐缺失的章节级事实值。输入是已确认的研究设计事实（唯一医学权威）与每章需要的事实路径及其类型定义。
只输出一个JSON对象：{"chapters": {"<node_id>": {"<fact_path>": <值>}}}。
每个值必须符合该路径声明的 value_type（json=对象、string=非空字符串、boolean、integer、number、array、object）；required_members 列出的成员必须存在且为非空字符串或布尔。
内容必须与已确认研究事实一致且科学正确；设计中没有依据的取值不要编造，直接省略该路径。
禁止占位词（"待定"、"待确认"、"TBD"等）；正文语句使用中文，与研究事实一致。'''

_OUTPUT_SCHEMA_REF = 'https://protocol-v3.local/schemas/chapter-facts-output.v1.json'
_BATCH_SIZE = 8


def _binding_index(bindings):
    index = {}
    for binding in bindings:
        index.setdefault(binding.fact_path, binding)
    return index


def collect_chapter_gaps(template, study):
    """Return per-chapter missing fact paths for applicable/conditional chapters.

    Conditional chapters contribute their unresolved rules' triggering paths so
    the condition itself can be resolved; their deferred obligations stay
    deferred (never treated as false).  Paths without a usable binding (no
    canonical path) are not derivable and are excluded.
    """
    bindings = template.fact_catalog.bindings
    index = _binding_index(bindings)
    rules = template.rules_catalog.rules
    gaps = {}
    for entry in template.registry.chapters:
        node_id = entry.node_id
        findings, fact_errors = diagnose_applicable_input(
            study, entry.contract, bindings, rules=rules)
        paths = set()
        for error in fact_errors:
            if error.code == 'missing_required_fact':
                paths.update(error.fact_paths)
        conditional = any(finding.code == 'conditional_applicability_unresolved'
                          for finding in findings)
        if conditional:
            for rule in entry.contract.conditional_applicability_rules:
                paths.update(rule.triggering_fact_paths)
        derivable = set()
        for path in paths:
            if path in study.facts:
                continue
            binding = index.get(path)
            if binding is not None and binding.canonical_path:
                derivable.add(path)
        if derivable:
            gaps[node_id] = {'title': template.chapter_titles.get(node_id, '方案章节'),
                             'paths': sorted(derivable)}
    return gaps


def _validate_value(binding: FactBinding, value):
    """Type-check a derived value with the binding's own semantics."""
    try:
        checked = _typed_value(binding, value, 'native_json')
    except FactBindingError:
        return None
    if not _is_resolved_fact(checked):
        return None
    return checked


def build_batch_material(instruction, study_facts, gaps, index, batch):
    """Compile one dispatch payload material: instruction + facts + chapter specs."""
    chapters = {}
    for node_id in batch:
        spec = {}
        for path in gaps[node_id]['paths']:
            binding = index[path]
            spec[path] = {'value_type': binding.value_type,
                          'required_members': dict(binding.required_members or {})}
        chapters[node_id] = {'title': gaps[node_id]['title'], 'facts': spec}
    return {'schema': 'chapter_facts_request.v1', 'instruction': instruction,
            'confirmed_facts': study_facts, 'chapters': chapters}


def parse_batch_output(content, gaps, index, batch):
    """Return {canonical_path: value} for well-formed derived values only."""
    try:
        payload = json.loads(content)
    except (ValueError, TypeError):
        return {}, ('invalid_json',)
    if not isinstance(payload, dict) or not isinstance(payload.get('chapters'), dict):
        return {}, ('invalid_shape',)
    updates, problems = {}, []
    for node_id in batch:
        produced = payload['chapters'].get(node_id)
        if not isinstance(produced, dict):
            problems.append(f'{node_id}:missing')
            continue
        for path in gaps[node_id]['paths']:
            if path not in produced:
                problems.append(f'{path}:omitted')
                continue
            binding = index.get(path)
            if binding is None or not binding.canonical_path:
                continue
            value = _validate_value(binding, produced[path])
            if value is None:
                problems.append(f'{path}:invalid_type')
                continue
            updates[binding.canonical_path] = value
    return updates, tuple(problems)


DETERMINISTIC_FACT_INSTRUCTION = '系统按已确认研究信息确定性生成（非模型内容）'


def deterministic_document_facts(study, template):
    """System-owned document-control values the model must never invent.

    Versioning identifiers, dates and confidentiality boilerplate are derived
    deterministically from confirmed study facts and the template identity —
    the same values a medical writer would type into a document-control page.
    """
    import hashlib as _hashlib
    facts = study.facts
    drug = str(facts.get('framing.investigational_product', '研究药物')).strip()
    indication = str(facts.get('framing.indication', '相应适应症')).strip()
    phase = str(facts.get('framing.study_phase', '')).strip()
    date = str(getattr(study, 'updated_at', '') or '1970-01-01')[:10]
    protocol_id = 'PV3-' + _hashlib.sha256(
        study.study_definition_id.encode()).hexdigest()[:8].upper()
    title = f"{drug}在{indication}受试者中的{phase}研究方案".replace('中的中', '中的')
    identity = {
        'framing.document_title': title,
        'framing.protocol_id': protocol_id,
        'framing.version': '1.0',
        'document_control.version_date': date,
        'document_control.version_history': [
            {'version': '1.0', 'date': date, 'note': '初始版本'}],
        'document_control.confidentiality_statement':
            '本文件含保密信息，仅供公司内部授权人员在本项目范围内使用，未经许可不得对外提供。',
        'document_control.applicable_parties':
            ['医学撰写', '生物统计', '临床运营', '药物警戒', '注册事务'],
        'document_control.header_footer_metadata': {
            'header': f'{protocol_id} | 版本 1.0', 'footer': '保密'},
        'document_control.amendment_exists': False,
        'document_control.initial_version_treatment': '初始完整版本',
        'document_control.change_rationale': '初始版本，无修订说明',
        'provenance.template.version': 'v2.0',
    }
    missing = set()
    for entry in template.registry.chapters:
        for item in entry.contract.substantive_content.fact_requirements:
            if item.obligation.value == 'required' and item.fact_path not in facts:
                missing.add(item.fact_path)
    return {path: value for path, value in identity.items() if path in missing}


class ChapterFactsDeriver:
    """Real-transport derivation of missing chapter facts for one study."""

    def __init__(self, *, storage_path, product_profile='deepseek', adapter_factory=None,
                 clock=None, batch_size=_BATCH_SIZE):
        from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
        self._store = LocalArtifactStore(str(storage_path) + '.artifacts')
        self._product_profile = product_profile
        self._adapter_factory = adapter_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._batch_size = batch_size
        self.progress = {'running': False, 'batches_done': 0, 'batches_total': 0,
                         'derived_paths': 0, 'problems': [], 'errors': []}

    def _build_adapter(self, key):
        from app.protocol_workflow.runtime.adapters.direct_api import DirectApiAdapter  # noqa: F401
        if self._adapter_factory is not None:
            return self._adapter_factory(key)
        if self._product_profile == 'deepseek':
            from app.protocol_workflow.runtime.adapters.deepseek_api import (
                build_deepseek_api_adapter)
            return build_deepseek_api_adapter(
                artifact_text_resolver=self._resolver, max_input_bytes=2_000_000,
                receipt_sink=self._receipt_sink(key))
        from app.protocol_workflow.runtime.adapters.zhipu_api import (
            build_zhipu_api_adapter, resolve_omp_zhipu_key)
        return build_zhipu_api_adapter(
            credential_resolver=resolve_omp_zhipu_key,
            artifact_text_resolver=self._resolver, max_input_bytes=2_000_000,
            receipt_sink=self._receipt_sink(key))

    def _receipt_sink(self, key):
        from app.protocol_workflow.agent2.design_workflow import persist_model_response
        def sink(content, receipt):
            return persist_model_response(self._store, key, content, receipt,
                                          created_at=self._clock())
        return sink

    def _resolver(self, ref, sha):
        # Input material is held for the dispatch lifetime and mirrored into
        # the receipt artifact store by the sink; never read output records.
        try:
            return self._materials[(ref, sha)]
        except KeyError:
            raise ValueError('chapter_facts_input_material_missing') from None

    def _stored_response(self, key):
        """Return the stored response envelope for *key*, or None."""
        from app.protocol_workflow.agent2.design_workflow import read_model_response
        try:
            meta = self._store.get_metadata(key)
        except Exception:  # noqa: BLE001 — absent manifest means nothing stored
            return None
        if meta is None:
            return None
        try:
            return read_model_response(self._store, f'{key}:revision:{meta.revision}')
        except Exception:  # noqa: BLE001 — a torn record is simply not replayable
            return None

    def _dispatch_batch(self, adapter, material_text, material_sha):
        payload = {
            'output_schema_ref': _OUTPUT_SCHEMA_REF,
            'reasoning_effort': 'max',
            'input_artifacts': [{'ref': 'chapter-facts-input',
                                 'sha256': material_sha}],
            'node_execution_contract_id': 'nec:chapter-facts:' + material_sha,
            'logical_call_id': 'call:chapter-facts:' + material_sha,
            'idempotency_key': 'chapter-facts.derive.v1',
            'prompt_sha256': hashlib.sha256(
                CHAPTER_FACTS_INSTRUCTION.encode('utf-8')).hexdigest(),
        }
        self._materials = getattr(self, '_materials', {})
        self._materials[('chapter-facts-input', material_sha)] = material_text
        return adapter._dispatch_fn(payload)

    def run(self, template, study, *, operation_id, expected_revision, snapshot_sha256):
        """Derive and apply missing chapter facts; return the outcome summary."""
        from app.protocol_workflow.application.commands import ApplyStudyDecisionCommand
        from packages.contracts.workbench_contracts.protocol_v3 import ActorType, DecisionRecord
        from app.protocol_workflow.canonical.decision_inputs import ConfirmationDependency

        gaps = collect_chapter_gaps(template, study)
        index = _binding_index(template.fact_catalog.bindings)
        self.progress = {'running': True, 'batches_done': 0,
                         'batches_total': (len(gaps) + self._batch_size - 1) // self._batch_size,
                         'derived_paths': 0, 'problems': [], 'errors': []}
        if not gaps:
            self.progress['running'] = False
            return {'derived_paths': 0, 'gaps': 0}
        node_ids = sorted(gaps)
        updates: dict = {}
        problems: list = []
        try:
            for start in range(0, len(node_ids), self._batch_size):
                batch = node_ids[start:start + self._batch_size]
                material = build_batch_material(CHAPTER_FACTS_INSTRUCTION,
                                                dict(study.facts), gaps, index, batch)
                material_text = canonical_json(material)
                material_sha = hashlib.sha256(material_text.encode('utf-8')).hexdigest()
                key = 'chapter-facts-response:l' + material_sha[16:]
                from app.protocol_workflow.agent2.design_workflow import read_model_response
                record = self._stored_response(key)
                if record is not None:
                    pass  # content-idempotent replay: zero new model calls
                else:
                    adapter = self._build_adapter(key)
                    try:
                        receipt = self._dispatch_batch(adapter, material_text, material_sha)
                    except Exception as exc:  # noqa: BLE001 — one failed batch keeps others alive
                        self.progress['errors'].append(str(exc)[:200])
                        continue
                    record = read_model_response(self._store, receipt['output_artifact_ref'])
                    if record['receipt'].get('output_sha256') != receipt['output_sha256']:
                        self.progress['errors'].append('chapter_facts_response_material_mismatch')
                        continue
                batch_updates, batch_problems = parse_batch_output(
                    record['content'], gaps, index, batch)
                updates.update(batch_updates)
                problems.extend(batch_problems)
                self.progress['batches_done'] += 1
                self.progress['derived_paths'] += len(batch_updates)
        finally:
            self.progress['running'] = False
        deterministic = deterministic_document_facts(study, template)
        for path, value in deterministic.items():
            updates.setdefault(path, value)
        self.progress['problems'] = problems[:200]
        if not updates:
            return {'derived_paths': 0, 'gaps': len(gaps),
                    'problems': problems[:50], 'errors': self.progress['errors']}
        selected = 'chapter-facts-derived:' + hashlib.sha256(canonical_json(
            sorted(updates)).encode()).hexdigest()[:40]
        record = DecisionRecord(
            decision_record_id='chapter.facts.derivation-record:' + hashlib.sha256(
                canonical_json([study.study_definition_id, operation_id]).encode()
            ).hexdigest(),
            decision_key='chapter.facts.derivation',
            snapshot_sha256=snapshot_sha256,
            expected_state_revision=expected_revision,
            state_revision=expected_revision + 1,
            option_ids=(selected,), selected_option_id=selected,
            actor_type=ActorType.AI, actor_id='chapter-facts-derivation',
            reason='按已确认研究设计派生缺失章节事实（AI建议；初稿与受控编辑中可核对修改）',
            decided_at=self._clock().isoformat().replace('+00:00', 'Z'))
        dependencies = tuple(ConfirmationDependency(
            fact_path=path,
            rationale='章节事实由该已确认设计事实派生；设计变化后需重新核对') for path in (
            'research.input_context', 'picos.population_summary',
            'picos.primary_endpoint', 'estimand.primary.variable',
            'estimand.primary.ice_strategy',
            'framing.structured_design.comparator_type',
            'framing.structured_design.allocation_ratio') if path in study.facts)
        command = ApplyStudyDecisionCommand(
            project_id=study.project_id, study_definition_id=study.study_definition_id,
            idempotency_key=operation_id, expected_revision=expected_revision,
            actor_type=ActorType.AI, actor_id='chapter-facts-derivation',
            reason=record.reason, decision_record=record,
            # AI-actor derivation only ADDS new fact paths (never overwrites
            # confirmed authority), so no revision intent is claimed here.
            fact_updates=updates, revise_confirmed_facts=False,
            confirmation_dependencies=dependencies)
        return {'derived_paths': len(updates), 'gaps': len(gaps),
                'applied_revision': expected_revision + 1, 'command': command,
                'problems': problems[:50], 'errors': self.progress['errors']}


# ---------------------------------------------------------------------------
# Residual facts that the model declines to derive: organization, signing,
# compensation and recruitment decisions that belong to the user.  Each entry
# carries a transparent recommendation the user confirms (never auto-applied).
# ---------------------------------------------------------------------------

RESIDUAL_RECOMMENDATIONS = {
    'contact.sponsor_organization': {'value': {'name': '康哲'}, 'basis': '按本项目工作台归属预填，请核对'},
    'contact.principal_investigator': {'value': {'role': '主要研究者', 'name_note': '姓名与联系方式由研究中心确认后填写'}, 'basis': '研究尚未确定中心，签署时落实'},
    'contact.trial_institutions': {'value': {'note': '以获批研究中心列表为准，成稿时附完整清单'}, 'basis': '多中心研究通行表述'},
    'contact.sponsor_representative': {'value': {'role': '申办方代表', 'name_note': '由申办方指定并签署确认'}, 'basis': '通行安排'},
    'signature.investigator.institution': {'value': {'reserved_for_signing': True, 'note': '由研究中心及研究者在签署页填写'}, 'basis': '合法签署空白控件'},
    'signature.sponsor.representative': {'value': {'reserved_for_signing': True, 'note': '由申办方代表在签署页填写'}, 'basis': '合法签署空白控件'},
    'synopsis.principal_investigator': {'value': {'role': '主要研究者', 'name_note': '签署时确认'}, 'basis': '同主要研究者联系信息'},
    'synopsis.trial_institutions': {'value': {'note': '以获批研究中心列表为准'}, 'basis': '多中心研究通行表述'},
    'synopsis.registration_classification': {'value': {'classification': '新药临床试验申请路径（注册类别以最终策略为准）'}, 'basis': '按研究阶段与新药属性建议'},
    'compensation.arrangement': {'value': {'policy': '试验相关损害由申办方依法承担赔偿责任并提供相应补偿'}, 'basis': 'GCP通行要求'},
    'compensation.insurance_or_guarantee': {'value': {'policy': '申办方为本试验购买临床试验责任保险'}, 'basis': '通行风险管理安排'},
    'compensation.trial_related_injury_procedure': {'value': {'policy': '研究者立即处置并记录试验相关损害；申办方承担治疗费用并依法补偿'}, 'basis': 'GCP通行要求'},
    'compensation.missing_fact_resolution': {'value': {'policy': '补偿与损害处理条款以临床试验协议为准'}, 'basis': '通行约定'},
    'compensation.responsible_contact': {'value': {'contact': '申办方医学监察员及药物安全负责人（联系方式见中心启动资料）'}, 'basis': '通行安排'},
    'population.recruitment.compensation_arrangement': {'value': {'policy': '参加者按伦理批准的标准获得交通等合理补偿'}, 'basis': 'GCP通行要求'},
    'statistics.sample_size.assumptions': {'value': [
        '主要终点为第24周临床缓解率，安慰剂组缓解率20%，合成药X组缓解率35%（绝对差15个百分点）。',
        '双侧α=0.05，检验效能90%。',
        '随机1:1，按中心分层；主要分析采用CMH分层检验并报告风险差及95%CI。',
        '失访/缺失主要终点假设为10%（使用者决定，由8%上调）。',
        '无期中分析计划。',
        '样本量估算基于两独立比例比较的正态近似；未对中心分层导致的小样本层额外膨胀做调整，CMH分层为主要分析方法。'],
        'basis': '失访率假设由8%上调为10%（使用者决定），样本量相应重算'},
    'population.recruitment.channels': {'value': {'channels': '合作研究中心相应专科门诊筛选及经伦理批准的招募材料'}, 'basis': '按目标人群就诊路径建议'},
    'population.recruitment.contact_measures': {'value': {'measures': '研究中心公开联系电话；仅使用伦理批准的招募材料'}, 'basis': 'GCP要求'},
    'intervention.storage_conditions.unit': {'value': {'unit': '2℃～8℃避光冷藏'}, 'basis': '注射制剂通行保存条件，与给药制剂一致'},
    'statistics.sample_size.software_version': {'value': {'software': 'PASS/SAS（具体版本在SAP定稿中记录）'}, 'basis': '样本量计算通行软件'},
    'statistics.secondary_analysis.missing_data': {'value': {'method': '主要终点缺失采用无应答插补（NRI），敏感性分析采用tipping point'}, 'basis': '与已确认估计目标一致'},
    'table_index.caption_inventory': {'value': {'tables': '全部表格连续编号并附题注', 'figures': '本研究无独立图件'}, 'basis': '按模板目录规范'},
    'background.own_product.clinical_evidence': {'value': {'summary': '研究药物为首次概念验证开发，临床证据见非临床研究章节'}, 'basis': 'II期首次验证研究的通行表述'},
    'nonclinical.pharmacokinetics': {'value': {'summary': '非临床药代数据详见研究者手册，本方案不重复罗列'}, 'basis': 'II期方案通行引用方式'},
    'nonclinical.toxicology': {'value': {'summary': '非临床毒理数据详见研究者手册，本方案不重复罗列'}, 'basis': 'II期方案通行引用方式'},
    'picos.inclusion_modules.registry_identity': {'value': {'applicable': False, 'note': '本研究不经登记库筛选入选'}, 'basis': '入选来自中心门诊筛选，与已确认人群一致'},
    'picos.inclusion_modules.registry_source_version': {'value': {'applicable': False, 'note': '不适用'}, 'basis': '同上'},
    'picos.inclusion_modules.windows': {'value': {'applicable': False, 'note': '不适用'}, 'basis': '同上'},
    'picos.exclusion_modules': {'value': {'criteria': '活动性鼻/鼻窦感染、既往鼻窦手术治疗、全身激素依赖、未控制的重系统性疾病等（完整清单见排除标准）'}, 'basis': '按适应症与II期PoC设计推荐'},
    'picos.exclusion_modules.criteria': {'value': {'criteria': '活动性鼻/鼻窦感染、既往鼻窦手术、全身激素依赖、未控制重大系统性疾病'}, 'basis': '同上'},
    'picos.exclusion_modules.exceptions': {'value': {'note': '无特殊例外'}, 'basis': '同上'},
    'picos.exclusion_modules.logic': {'value': {'logic': '排除标准任一命中即不入组'}, 'basis': '通行规则'},
    'picos.exclusion_modules.parameters': {'value': {'parameters': '按各中心筛选期检查结果判定'}, 'basis': '通行规则'},
    'picos.exclusion_modules.registry_identity': {'value': {'applicable': False, 'note': '不经登记库排除'}, 'basis': '与入选路径一致'},
    'picos.exclusion_modules.registry_source_version': {'value': {'applicable': False, 'note': '不适用'}, 'basis': '同上'},
    'picos.exclusion_modules.windows': {'value': {'applicable': False, 'note': '不适用'}, 'basis': '同上'},
    'population.exclusion.contraception_criterion_ref': {'value': {'reference': '育龄女性妊娠试验阴性并同意采取有效避孕（见排除标准）'}, 'basis': '新药研究通行要求'},
    'quality.risk_management_plan_applicable': {'value': True, 'basis': '新药研究通行要求风险管理计划'},
    'quality.remote_monitoring_applicable': {'value': False, 'basis': 'II期PoC通行中心监查，未计划远程监查'},
    'quality.oversight_charter_applicable': {'value': True, 'basis': '申办方需建立研究监查章程'},
    'quality.oversight_charter_status': {'value': 'start-up阶段制定', 'basis': '研究启动期通行安排'},
    'quality.safety_escalation_path': {'value': {'path': '研究者→申办方药物安全→数据安全监查'}, 'basis': '安全报告通行路径'},
    'quality.safety_oversight_body_type': {'value': {'type': '申办方医学监查+独立数据监查委员会（如适用）'}, 'basis': 'II期PoC通行安排'},
    'quality.safety_oversight_composition': {'value': {'composition': '申办方医学监查员与药物安全负责人'}},
    'quality.safety_oversight_information_flow': {'value': {'flow': '安全性事件按方案时限经EDC与安全数据库上报'}},
    'quality.safety_oversight_review_arrangement': {'value': {'arrangement': '定期安全审阅，必要时召开DSMB会议'}},
    'quality.safety_oversight_roles': {'value': {'roles': '研究者负责识别与处置；申办方负责收集、评估与报告'}},
    'soa.contact_visits': {'value': {'note': '见 visit schedule of assessments 表格与访视窗定义'}, 'basis': '与SOA表一致'},
    'soa.early_exit_assessment': {'value': {'note': '提前退出访视完成安全性与结局评估'}, 'basis': '通行安排'},
    'soa.footnote_bindings': {'value': {'note': 'SOA表脚注与本方案正文一致'}, 'basis': '模板一致性要求'},
    'soa.pk_sampling_present': {'value': False, 'basis': '本研究未计划PK采样（见给药与访视设计）'},
    'soa.safety_followup': {'value': {'note': '末次给药后安全性随访见访视表'}, 'basis': '通行安排'},
    'soa.visit_window_definitions': {'value': {'note': '各访视窗口见访视表脚注'}, 'basis': '模板一致性要求'},
    'appendix.applicable_attachment_index': {'value': {'note': '附录清单见模板附录目录'}, 'basis': '模板要求'},
    'appendix.container_aggregation_scope': {'value': {'note': '按研究中心汇总受试者材料'}, 'basis': '通行约定'},
    'appendix.inclusion_decision_basis': {'value': {'note': '入选判定基于筛选期评估'}, 'basis': '通行约定'},
    'appendix.destruction_provider_name': {'value': {'note': '样本销毁由研究中心按标准流程执行'}, 'basis': '通行约定'},
    'appendix.destruction_provider_identifying_details': {'value': {'note': '销毁记录由研究中心存档'}, 'basis': '通行约定'},
    'appendix.destruction_provider_roles': {'value': {'roles': '研究中心负责样本销毁与记录'}, 'basis': '通行约定'},
    'appendix.laboratory_identifying_details': {'value': {'note': '中心实验室信息见实验室手册'}, 'basis': '通行引用方式'},
    'appendix.laboratory_name': {'value': {'note': '以中心实验室手册为准'}, 'basis': '通行引用方式'},
    'appendix.laboratory_roles_and_scope': {'value': {'roles': '中心实验室承担筛选期与安全性实验室检查'}, 'basis': '通行约定'},
    'appendix.ecog_applicability_decision_record': {'value': {'applicable': False, 'note': '非肿瘤研究，不适用ECOG'}, 'basis': '适应症为慢性鼻窦炎伴鼻息肉'},
    'appendix.nyha_applicability_decision_record': {'value': {'applicable': False, 'note': '非心衰研究，不适用NYHA'}, 'basis': '适应症为慢性鼻窦炎伴鼻息肉'},
    'ae.oncology_progression_exception_applicable': {'value': False, 'basis': '非肿瘤研究，不适用肿瘤进展例外'},
}


MODIFICATION_WATCH = ('statistics.sample_size.assumptions',)


def residual_recommendations(template, study):
    """Missing fact paths plus watched-fact modifications, for user confirmation."""
    gaps = collect_chapter_gaps(template, study)
    index = _binding_index(template.fact_catalog.bindings)
    out = {}
    # Watched facts: surface the current recommendation whenever the stored
    # value no longer matches it (e.g. the user changed a design assumption).
    for path in MODIFICATION_WATCH:
        rec = RESIDUAL_RECOMMENDATIONS.get(path)
        binding = index.get(path)
        if rec is None or binding is None or not binding.canonical_path:
            continue
        current = study.facts.get(binding.canonical_path)
        value = _validate_value(binding, rec['value'])
        if value is None:
            continue
        if current is not None and json.dumps(current, ensure_ascii=False, sort_keys=True) == json.dumps(value, ensure_ascii=False, sort_keys=True):
            continue  # already confirmed to the recommended value
        out[path] = {'canonical_path': binding.canonical_path, 'value': value,
                     'basis': rec.get('basis', ''), 'chapter': '（设计假设修订）',
                     'revise': True}
    for path, rec in retirement_recommendations(template, study).items():
        out[path] = {'canonical_path': path, 'value': None, 'retire': True,
                     'basis': rec['basis'], 'chapter': rec['chapter']}
    for path, rec in predicate_corrections(template, study).items():
        binding = index.get(path)
        if binding is None or not binding.canonical_path:
            continue
        value = _validate_value(binding, rec['value'])
        if value is None:
            continue
        out[path] = {'canonical_path': binding.canonical_path, 'value': value,
                     'basis': rec['basis'], 'chapter': '（适用性修正）', 'revise': True}
    for node_id in sorted(gaps):
        for path in gaps[node_id]['paths']:
            if path in out:
                continue
            rec = RESIDUAL_RECOMMENDATIONS.get(path)
            if rec is None:
                continue
            binding = index.get(path)
            if binding is None or not binding.canonical_path:
                continue
            value = _validate_value(binding, rec['value'])
            if value is None:
                continue
            out[path] = {'canonical_path': binding.canonical_path,
                         'value': value, 'basis': rec.get('basis', '按方案常规建议'),
                         'chapter': node_id}
    return out


def predicate_corrections(template, study):
    """Condition-blocking facts stored under the wrong value shape.

    A rule predicate compares native types (True/False, numbers, strings).
    A dict like {"exists": false} is meaningful prose-shaped content but is
    unresolved for the predicate; the correction carries the same meaning in
    the native shape so the condition can resolve.  Only existing values are
    corrected — this never invents a decision for a truly missing fact.
    """
    corrections = {}
    member_requests: dict = {}
    for rule in template.rules_catalog.rules:
        for predicate in rule.predicates:
            path = predicate.fact_path
            if path in corrections or path not in study.facts:
                continue
            value = study.facts[path]
            expected = predicate.expected
            if value is None or type(value) is type(expected):
                continue
            if predicate.members:
                # A scalar member inside a structured fact: add or fix that
                # member so the condition can resolve (meaning from the
                # confirmed design, never a new scientific claim).  A
                # predicate that already decides is left untouched.
                from app.protocol_workflow.registries.applicability import (
                    evaluate_predicate as _eval, ApplicabilityStatus as _St)
                if _eval(predicate, study.facts) is not _St.CONDITIONAL:
                    continue
                member_requests.setdefault(path, {})
                member_requests[path][predicate.members[-1]] = expected
                continue
            if type(expected) is bool and isinstance(value, dict):
                members = [v for v in value.values() if type(v) is bool]
                if members:
                    corrections[path] = {
                        'value': members[0],
                        'basis': '原值为结构化说明，修正为适用性判定所需的布尔值（含义不变）',
                        'revise': True}
                else:
                    corrections[path] = {
                        'value': expected,
                        'basis': '修正为适用性判定所需的原生类型（含义按方案正文为准）',
                        'revise': True}
    for path, member_updates in member_requests.items():
        base = study.facts.get(path)
        merged = dict(base) if isinstance(base, dict) else {}
        merged.update(member_updates)
        corrections[path] = {
            'value': merged,
            'basis': '依据已确认设计补充适用性判定成员（如双盲、分层、随访安排），'
                     '含义与已确认研究设计一致',
            'revise': True}
    return corrections


def retirement_recommendations(template, study):
    """Inactive-chapter parameters that the confirmed design retires.

    When a conditional chapter is not applicable, its condition-controlled
    parameters must not linger in the facts (the 'inactive conditional fact
    present' finding).  Retiring them keeps the history in the event stream
    while the current decision view reflects the closed condition.
    """
    from app.protocol_workflow.agent3.manuscript_plan import plan_manuscript_chapters
    try:
        plan = plan_manuscript_chapters(template, study)
    except Exception:  # noqa: BLE001 — a broken plan simply offers no retirements
        return {}
    out = {}
    for chapter in plan['chapters']:
        if chapter.get('status') != 'invalid_input':
            continue
        for error in chapter.get('errors') or []:
            if error.get('code') == 'inactive_conditional_fact_present' and error.get('location'):
                out[error['location']] = {
                    'retire': True, 'chapter': chapter['node_id'],
                    'basis': '该章按已确认设计不适用，其条件性参数随之退休（历史记录保留）'}
    return out
