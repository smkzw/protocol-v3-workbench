#!/usr/bin/env python3
"""Generate a deterministic quality audit for the medical-writing corpus."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from services.api.app.medical_writing_company_corpus import (
    SNAPSHOT_PATH,
    MedicalWritingCompanyCorpusService,
)
from services.api.app.medical_writing_corpus_policy import (
    project_fact_slots,
    quality_flags,
    row_domain_tags,
    source_policy,
    text_quality,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT
    / "records/active_slices/medical_writing_corpus_quality_governance_20260715"
    / "CORPUS_QUALITY_AUDIT_20260716.json"
)

TERM_PATTERNS = {
    "participant_受试者": r"受试者",
    "participant_试验参与者": r"试验参与者",
    "participant_研究参与者": r"研究参与者",
    "participant_患者": r"患者",
    "intervention_试验药物": r"试验药物",
    "intervention_研究药物": r"研究药物",
    "intervention_试验干预": r"试验干预",
    "synopsis_方案概要": r"方案概要",
    "synopsis_方案摘要": r"方案摘要",
}

CONFLICT_PROBES = {
    "ae_mh_boundary": r"首剂前|首次给药前|病史|不良事件|AE",
    "analysis_set": r"全分析集|FAS|意向治疗|ITT|符合方案集|PPS|安全性集",
    "estimand": r"估计目标|estimand|伴发事件",
    "infection_screening": r"HCV|丙型肝炎|RNA|抗体阳性|活动性感染",
    "regulatory_version": r"MedDRA|CTCAE|ICH\s*E6|GCP",
    "contraception": r"避孕|育龄|妊娠试验|hCG|FSH",
    "soa": r"研究流程表|研究日|访视窗|访视窗口|试验阶段",
}

GOLDEN_QUERIES = (
    {
        "id": "pnh_synopsis_dose",
        "query": "具体服药剂量及频率",
        "section_heading": "方案概要",
        "section_number": "1.1",
        "project_indication": "阵发性睡眠性血红蛋白尿症",
        "expected_empty": True,
    },
    {
        "id": "ra_soa",
        "query": "访视 研究阶段 研究日",
        "section_heading": "研究流程表",
        "section_number": "1.3",
        "project_indication": "类风湿关节炎",
        "project_phase": "IIb期",
        "expected_source_regex": r"^MY004-RA-2b",
    },
    {
        "id": "ad_eligibility",
        "query": "特应性皮炎 入选标准 EASI",
        "section_heading": "入选标准",
        "section_number": "5.1",
        "project_indication": "特应性皮炎",
        "expected_source_regex": r"AD|炎症性皮肤病",
        "expected_text_regex": r"入选标准|纳入标准|符合.{0,30}(?:入选|纳入)|年龄|诊断|筛选期.{0,30}EASI",
    },
    {
        "id": "sae_reporting",
        "query": "严重不良事件 报告 随访",
        "section_heading": "严重不良事件报告",
        "section_number": "9.2",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_regex": r"严重不良事件.{0,30}(?:记录|报告)|(?:记录|报告).{0,30}严重不良事件",
    },
    {
        "id": "ethics_consent",
        "query": "伦理委员会 知情同意 GCP",
        "section_heading": "伦理与知情同意",
        "section_number": "11.2",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_regex": r"知情同意|伦理委员会|GCP",
    },
    {
        "id": "analysis_sets",
        "query": "全分析集 符合方案集 安全性集",
        "section_heading": "分析集",
        "section_number": "10.2",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_all_regex": (r"全分析集|FAS|ITT", r"符合方案集|PPS", r"安全性分析集|安全性集|SS"),
    },
    {
        "id": "references",
        "query": "参考文献 文献目录",
        "section_heading": "参考文献",
        "section_number": "14",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_regex": r"参考文献|bibliograph",
    },
    {
        "id": "concomitant_medication",
        "query": "合并用药 禁止使用 限制使用 洗脱期",
        "section_heading": "既往及合并治疗",
        "section_number": "6.10",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_regex": r"(?:禁止|限制|允许|不得|洗脱|可继续).{0,80}(?:合并用药|合并治疗|药物|治疗)|(?:合并用药|合并治疗|禁用药|限制用药).{0,80}(?:禁止|限制|允许|洗脱|继续使用)",
    },
    {
        "id": "dose_modification",
        "query": "剂量暂停 减量 重新给药 永久停药",
        "section_heading": "剂量调整规则",
        "section_number": "6.4",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_all_regex": (r"暂停.{0,12}给药|给药中断|剂量调整|减量", r"恢复给药|重新给药|终止治疗|永久停药"),
    },
    {
        "id": "hcg_fsh",
        "query": "妊娠检查 hCG FSH",
        "section_heading": "妊娠检查",
        "section_number": "8.4",
        "expected_text_regex": r"FSH|hCG",
    },
    {
        "id": "withdrawal",
        "query": "提前终止 退出研究 失访",
        "section_heading": "退出研究",
        "section_number": "7.2",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_regex": r"提前终止|退出研究|失访",
    },
    {
        "id": "laboratory",
        "query": "临床实验室 血常规 生化 尿常规",
        "section_heading": "临床实验室检查",
        "section_number": "8.3",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_regex": r"临床实验室|血常规|生化|尿常规",
    },
    {
        "id": "obesity_synopsis",
        "query": "超重 肥胖 剂量探索 方案概要",
        "section_heading": "方案概要",
        "section_number": "1.1",
        "project_indication": "超重或肥胖",
        "project_phase": "II期",
        "expected_source_regex": r"^CMS-D005-减重II期.*clean",
        "forbidden_source_regex": r"XY0525\.docx$",
    },
    {
        "id": "ra_positive_control_design",
        "query": "类风湿关节炎 阳性药 安慰剂对照 剂量探索",
        "section_heading": "研究设计",
        "section_number": "4.1",
        "project_indication": "类风湿关节炎",
        "project_phase": "IIb期",
        "expected_source_regex": r"^MY004-RA-2b",
    },
    {
        "id": "skin_poc_design",
        "query": "炎症性皮肤病 PoC 药效学 皮肤活检",
        "section_heading": "研究设计",
        "section_number": "4.1",
        "project_indication": "特应性皮炎",
        "expected_source_regex": r"^MY004567片-炎症性皮肤病",
    },
    {
        "id": "pnh_soa",
        "query": "PNH 研究流程表 访视 研究日",
        "section_heading": "研究流程表",
        "section_number": "1.3",
        "project_indication": "阵发性睡眠性血红蛋白尿症",
        "expected_source_regex": r"^CMS-D017-PNH-方案摘要",
    },
    {
        "id": "ad_phase3_soa",
        "query": "特应性皮炎 III期 研究流程表 访视",
        "section_heading": "研究流程表",
        "section_number": "1.3",
        "project_indication": "特应性皮炎",
        "project_phase": "III期",
        "expected_role": "full_protocol_style_and_clause_reference",
    },
    {
        "id": "csu_phase3_design",
        "query": "慢性自发性荨麻疹 III期 多中心 随机 双盲 安慰剂对照",
        "section_heading": "研究设计",
        "section_number": "4.1",
        "project_indication": "慢性自发性荨麻疹",
        "project_phase": "III期",
        "expected_source_regex": r"^1-3-4-1-2临床试验方案",
    },
    {
        "id": "ae_definition",
        "query": "不良事件 定义 首次给药前 病史",
        "section_heading": "不良事件定义",
        "section_number": "9.2",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_all_regex": (r"首次(?:接受试验用药品|给药|用药)前", r"病史|伴随疾病", r"不良事件|AE", r"记录|报告"),
    },
    {
        "id": "sae_criteria",
        "query": "导致死亡 危及生命 住院 严重不良事件",
        "section_heading": "严重不良事件定义",
        "section_number": "9.2",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_all_regex": (r"导致死亡|出现死亡", r"危及生命|住院"),
    },
    {
        "id": "pregnancy_reporting",
        "query": "妊娠报告 随访 配偶 妊娠结局",
        "section_heading": "妊娠报告",
        "section_number": "9.4",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_regex": r"妊娠.{0,40}(?:报告|随访|结局)",
    },
    {
        "id": "overdose",
        "query": "药物过量 报告 医学监测",
        "section_heading": "药物过量",
        "section_number": "9.5",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_regex": r"药物过量|过量用药",
    },
    {
        "id": "randomization_blinding",
        "query": "随机化 盲法 揭盲",
        "section_heading": "随机化与盲法",
        "section_number": "4.2",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_all_regex": (r"随机化|随机分配", r"盲法|设盲|揭盲|盲底"),
    },
    {
        "id": "investigational_product_accountability",
        "query": "试验药物 接收 储存 发放 回收 销毁",
        "section_heading": "试验药物管理",
        "section_number": "6.6",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_regex": r"接收|储存|发放|回收|销毁",
    },
    {
        "id": "non_investigational_intervention",
        "query": "非试验用药 背景治疗 救援治疗",
        "section_heading": "非试验用药或治疗",
        "section_number": "6.9",
        "expected_text_regex": r"非试验|背景治疗|救援治疗",
    },
    {
        "id": "ecg_assessment",
        "query": "12导联心电图 QTcF 安全性评估",
        "section_heading": "心电图检查",
        "section_number": "8.3",
        "expected_text_regex": r"心电图|QTcF",
    },
    {
        "id": "vital_signs",
        "query": "生命体征 血压 脉搏 体温",
        "section_heading": "生命体征",
        "section_number": "8.3",
        "expected_text_regex": r"生命体征",
    },
    {
        "id": "efficacy_assessment_ra",
        "query": "ACR20 DAS28 类风湿关节炎 疗效评估",
        "section_heading": "疗效评估",
        "section_number": "8.1",
        "project_indication": "类风湿关节炎",
        "expected_source_regex": r"^MY004-RA-2b",
    },
    {
        "id": "efficacy_assessment_ad",
        "query": "EASI IGA 特应性皮炎 疗效评估",
        "section_heading": "疗效评估",
        "section_number": "8.1",
        "project_indication": "特应性皮炎",
        "expected_source_regex": r"AD|炎症性皮肤病",
    },
    {
        "id": "sample_size",
        "query": "样本量 假设 把握度 显著性水平",
        "section_heading": "样本量",
        "section_number": "10.1",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_regex": r"样本量|把握度|显著性水平",
    },
    {
        "id": "multiplicity",
        "query": "多重性控制 I类错误",
        "section_heading": "多重性控制",
        "section_number": "10.4",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_regex": r"多重性|I类错误|Ⅰ类错误",
    },
    {
        "id": "missing_data",
        "query": "缺失数据 敏感性分析",
        "section_heading": "缺失数据处理",
        "section_number": "10.5",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_regex": r"缺失数据|敏感性分析",
    },
    {
        "id": "estimand",
        "query": "估计目标 伴发事件策略 目标人群 变量",
        "section_heading": "估计目标",
        "section_number": "3.1",
        "expected_text_all_regex": (r"目标人群", r"治疗|处理", r"变量|终点", r"伴发事件", r"群体层面汇总|总体效应度量"),
    },
    {
        "id": "confidentiality",
        "query": "保密声明 伦理委员会 监督管理部门",
        "section_heading": "首页保密声明",
        "section_number": "0",
        "expected_text_regex": r"保密声明",
    },
    {
        "id": "publication_policy",
        "query": "研究结果 发表政策 出版",
        "section_heading": "发表政策",
        "section_number": "11.9",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_regex": r"发表|出版|研究结果",
    },
    {
        "id": "quality_management",
        "query": "质量管理 监查 稽查 检查",
        "section_heading": "质量管理",
        "section_number": "11.7",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_regex": r"质量保证|质量控制|质量管理(?!规范)|监查计划|稽查计划",
    },
    {
        "id": "data_management",
        "query": "数据管理 数据库锁定 数据更正",
        "section_heading": "数据管理",
        "section_number": "11.6",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_all_regex": (r"EDC|eCRF|数据采集|数据录入|数据清理|数据库锁定", r"数据更正|数据质疑|数据库.{0,20}修改|数据核查|数据导出"),
    },
    {
        "id": "hcv_screening",
        "query": "HCV抗体 HCV RNA 活动性感染 排除标准",
        "section_heading": "排除标准",
        "section_number": "5.2",
        "expected_text_all_regex": (r"HCV|丙型肝炎", r"抗体", r"RNA|活动性感染"),
    },
    {
        "id": "contraception",
        "query": "育龄女性 避孕 方法 持续时间",
        "section_heading": "避孕要求",
        "section_number": "5.4",
        "expected_text_regex": r"避孕|育龄",
    },
    {
        "id": "rescreening",
        "query": "再次筛选 筛选失败",
        "section_heading": "再次筛选",
        "section_number": "5.3",
        "expected_text_regex": r"再次筛选|重新筛选|重复筛选",
    },
    {
        "id": "end_of_study",
        "query": "研究结束 EOS 治疗结束 EOT",
        "section_heading": "研究结束",
        "section_number": "7.3",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_all_regex": (r"研究结束|EOS", r"治疗结束|EOT"),
    },
    {
        "id": "adolescent_assent",
        "query": "青少年 知情同意 法定代理人",
        "section_heading": "知情同意",
        "section_number": "11.2",
        "project_indication": "特应性皮炎",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_all_regex": (r"青少年|未成年人", r"监护人|法定代理人", r"知情同意|同意书|ICF"),
    },
    {
        "id": "ae_general_definition",
        "query": "不良事件 是指 任何不利医学事件 不一定有因果关系",
        "section_heading": "不良事件定义",
        "section_number": "9.2",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_all_regex": (r"不良事件|AE", r"不良医学事件", r"不一定.{0,30}因果关系"),
        "forbidden_text_regex": r"^治疗期出现的不良事件",
    },
    {
        "id": "sae_24h_reporting",
        "query": "严重不良事件 SAE 获知后24小时 报告 申办者",
        "section_heading": "严重不良事件报告",
        "section_number": "9.3",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_all_regex": (r"SAE|严重不良事件", r"24\s*小时", r"申办者", r"报告"),
    },
    {
        "id": "ae_mh_boundary_explicit",
        "query": "首次给药前 病史 首次给药后 不良事件 AE",
        "section_heading": "不良事件与病史边界",
        "section_number": "9.2",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_all_regex": (r"首次给药前|首次用药之前", r"病史|伴随疾病", r"AE|不良事件", r"记录|报告"),
    },
    {
        "id": "consent_before_procedure",
        "query": "签署知情同意前 不可进行试验相关程序",
        "section_heading": "知情同意过程",
        "section_number": "11.2",
        "expected_text_all_regex": (r"签署知情同意书前", r"不可|不得", r"试验相关程序|研究相关程序"),
    },
    {
        "id": "drug_accountability_lifecycle",
        "query": "试验药物 接收 储存 发放 回收 销毁",
        "section_heading": "试验药物管理",
        "section_number": "6.6",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_all_regex": (r"接收|收到", r"储存|贮存|保存", r"发放|分发", r"回收|返还", r"销毁|统一处理"),
        "expected_reconstruction": True,
    },
    {
        "id": "data_lock_change_control",
        "query": "数据库锁定后 修改 申请 签字确认 数据导出",
        "section_heading": "数据管理",
        "section_number": "11.6",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_all_regex": (r"数据库锁定后", r"修改", r"申请", r"签字确认", r"数据.{0,20}导出|EDC"),
    },
    {
        "id": "soa_note_substantive",
        "query": "研究流程表 附注 血常规 检查项目",
        "section_heading": "研究流程表附注",
        "section_number": "1.3",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_regex": r"血常规|附注|注：",
        "forbidden_text_regex": r"^表\s*\d+(?:\.\d+)*[.．、\s].*研究流程表$",
    },
    {
        "id": "version_sensitive_safety_reference",
        "query": "MedDRA CTCAE 版本 安全性编码 分级",
        "section_heading": "安全性分析",
        "section_number": "10.7",
        "expected_role": "full_protocol_style_and_clause_reference",
        "expected_text_all_regex": (r"MedDRA", r"CTCAE"),
        "expected_quality_flag": "version_sensitive_terminology",
    },
)


def normalized_text(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def source_stats(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("source_file") or "")].append(row)
    result: list[dict[str, Any]] = []
    for source_file, items in sorted(grouped.items()):
        policy = source_policy(source_file)
        result.append(
            {
                "source_file": source_file,
                "entry_count": len(items),
                "governance_status": policy.governance_status,
                "authority_by_function": policy.authority_by_function,
                "block_types": dict(Counter(str(item.get("block_type") or "") for item in items)),
                "reuse_levels": dict(Counter(str(item.get("reuse_level") or "") for item in items)),
                "domain_counts": dict(
                    Counter(domain for item in items for domain in row_domain_tags(item))
                ),
                "project_fact_entry_count": sum(
                    bool(project_fact_slots(str(item.get("text") or ""))) for item in items
                ),
                "zero_quality_entry_count": sum(text_quality(item)[0] == 0.0 for item in items),
            }
        )
    return result


def exact_cross_source_duplicates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        text = str(row.get("text") or "")
        key = normalized_text(text)
        if len(key) >= 24:
            groups[key].append(row)
    result: list[dict[str, Any]] = []
    for items in groups.values():
        sources = sorted({str(item.get("source_file") or "") for item in items})
        if len(sources) < 2:
            continue
        result.append(
            {
                "source_count": len(sources),
                "entry_count": len(items),
                "sources": sources,
                "text": str(items[0].get("text") or "")[:1000],
            }
        )
    return sorted(result, key=lambda item: (-item["source_count"], -item["entry_count"], item["text"]))


def flagged_entries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    quality_counter: Counter[str] = Counter()
    examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        text = str(row.get("text") or "")
        _, text_flags = text_quality(row)
        flags = sorted(set(text_flags + quality_flags(text)))
        for flag in flags:
            quality_counter[flag] += 1
            if len(examples[flag]) < 5:
                examples[flag].append(
                    {
                        "source_file": str(row.get("source_file") or ""),
                        "entry_id": str(row.get("entry_id") or ""),
                        "text": text[:700],
                    }
                )
    return {"counts": dict(quality_counter), "examples": dict(examples)}


def terminology_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    overall: Counter[str] = Counter()
    for row in rows:
        source = str(row.get("source_file") or "")
        text = str(row.get("text") or "")
        for label, pattern in TERM_PATTERNS.items():
            count = len(re.findall(pattern, text, re.I))
            if count:
                overall[label] += count
                by_source[source][label] += count
    return {
        "overall": dict(overall),
        "by_source": {source: dict(counts) for source, counts in sorted(by_source.items())},
    }


def conflict_probe_samples(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for probe, pattern in CONFLICT_PROBES.items():
        matching = [row for row in rows if re.search(pattern, str(row.get("text") or ""), re.I)]
        source_counts = Counter(str(row.get("source_file") or "") for row in matching)
        examples = []
        for row in matching:
            if len(examples) >= 12:
                break
            examples.append(
                {
                    "source_file": str(row.get("source_file") or ""),
                    "entry_id": str(row.get("entry_id") or ""),
                    "text": str(row.get("text") or "")[:900],
                }
            )
        result[probe] = {
            "entry_count": len(matching),
            "source_counts": dict(source_counts),
            "examples": examples,
        }
    return result


def run_golden_queries(service: MedicalWritingCompanyCorpusService) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for query_case in GOLDEN_QUERIES:
        request = {key: value for key, value in query_case.items() if key not in {
            "id", "expected_source_regex", "expected_role", "expected_text_regex",
            "expected_text_all_regex", "expected_empty",
            "expected_reconstruction", "expected_quality_flag",
            "forbidden_source_regex", "forbidden_text_regex",
        }}
        items = service.search(**request, limit=5)
        top = items[0] if items else {}
        passed = not items if query_case.get("expected_empty") else bool(items)
        if query_case.get("expected_source_regex"):
            passed = passed and bool(re.search(query_case["expected_source_regex"], str(top.get("source_file") or "")))
        if query_case.get("expected_role"):
            passed = passed and top.get("source_role") == query_case["expected_role"]
        if query_case.get("expected_text_regex"):
            passed = passed and bool(re.search(query_case["expected_text_regex"], str(top.get("text") or ""), re.I))
        if query_case.get("expected_text_all_regex"):
            passed = passed and all(
                re.search(pattern, str(top.get("text") or ""), re.I)
                for pattern in query_case["expected_text_all_regex"]
            )
        if query_case.get("expected_reconstruction"):
            passed = passed and bool(top.get("selection", {}).get("reconstruction"))
        if query_case.get("expected_quality_flag"):
            passed = passed and query_case["expected_quality_flag"] in top.get("selection", {}).get("quality_flags", [])
        if query_case.get("forbidden_source_regex"):
            passed = passed and not bool(re.search(query_case["forbidden_source_regex"], str(top.get("source_file") or "")))
        if query_case.get("forbidden_text_regex"):
            passed = passed and not bool(re.search(query_case["forbidden_text_regex"], str(top.get("text") or ""), re.I))
        cases.append(
            {
                "id": query_case["id"],
                "passed": passed,
                "request": request,
                "top_results": [
                    {
                        "rank": index,
                        "source_file": item.get("source_file"),
                        "source_role": item.get("source_role"),
                        "entry_id": item.get("entry_id"),
                        "score": item.get("retrieval_score"),
                        "selection": item.get("selection"),
                        "text": str(item.get("text") or "")[:900],
                    }
                    for index, item in enumerate(items, start=1)
                ],
            }
        )
    return {
        "passed": all(case["passed"] for case in cases),
        "passed_count": sum(case["passed"] for case in cases),
        "case_count": len(cases),
        "cases": cases,
    }


def build_audit(snapshot_path: Path) -> dict[str, Any]:
    rows = load_rows(snapshot_path)
    service = MedicalWritingCompanyCorpusService(snapshot_path=snapshot_path)
    domain_counts = Counter(domain for row in rows for domain in row_domain_tags(row))
    block_counts = Counter(str(row.get("block_type") or "") for row in rows)
    project_fact_counts = Counter(
        slot for row in rows for slot in project_fact_slots(str(row.get("text") or ""))
    )
    return {
        "schema_version": "medical_writing_corpus_quality_audit_v1",
        "snapshot_path": str(snapshot_path),
        "snapshot_definition": service.definition().model_dump(),
        "entry_count": len(rows),
        "source_count": len({str(row.get("source_file") or "") for row in rows}),
        "block_counts": dict(block_counts),
        "domain_counts": dict(domain_counts),
        "project_fact_slot_counts": dict(project_fact_counts),
        "source_stats": source_stats(rows),
        "terminology": terminology_stats(rows),
        "quality_flags": flagged_entries(rows),
        "exact_cross_source_duplicates": exact_cross_source_duplicates(rows),
        "conflict_probe_samples": conflict_probe_samples(rows),
        "golden_queries": run_golden_queries(service),
    }


def compact_summary(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": audit["schema_version"],
        "snapshot_definition": audit["snapshot_definition"],
        "entry_count": audit["entry_count"],
        "source_count": audit["source_count"],
        "block_counts": audit["block_counts"],
        "domain_counts": audit["domain_counts"],
        "project_fact_slot_counts": audit["project_fact_slot_counts"],
        "source_stats": audit["source_stats"],
        "terminology": audit["terminology"],
        "quality_flag_counts": audit["quality_flags"]["counts"],
        "quality_flag_examples": audit["quality_flags"]["examples"],
        "exact_cross_source_duplicate_group_count": len(audit["exact_cross_source_duplicates"]),
        "exact_cross_source_duplicate_examples": audit["exact_cross_source_duplicates"][:12],
        "conflict_probe_counts": {
            probe: {
                "entry_count": payload["entry_count"],
                "source_counts": payload["source_counts"],
            }
            for probe, payload in audit["conflict_probe_samples"].items()
        },
        "golden_queries": {
            "passed": audit["golden_queries"]["passed"],
            "passed_count": audit["golden_queries"]["passed_count"],
            "case_count": audit["golden_queries"]["case_count"],
            "cases": [
                {
                    "id": case["id"],
                    "passed": case["passed"],
                    "request": case["request"],
                    "top_result": case["top_results"][0] if case["top_results"] else None,
                }
                for case in audit["golden_queries"]["cases"]
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    audit = build_audit(args.snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary_path = args.output.with_name(f"{args.output.stem}_SUMMARY.json")
    summary_path.write_text(
        json.dumps(compact_summary(audit), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(args.output),
        "summary_output": str(summary_path),
        "entry_count": audit["entry_count"],
        "source_count": audit["source_count"],
        "duplicate_groups": len(audit["exact_cross_source_duplicates"]),
        "golden_queries": {
            "passed": audit["golden_queries"]["passed_count"],
            "total": audit["golden_queries"]["case_count"],
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
