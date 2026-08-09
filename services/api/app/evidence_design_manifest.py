from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from packages.contracts.workbench_contracts import (
    CompetitiveProductSummary,
    CompetitiveResultEndpointSummary,
    CompetitiveTrialDesignSummary,
    EvidenceCandidateDetail,
    EvidenceCandidatePage,
    EvidenceDesignManifestResult,
    EvidenceDesignPackageSummary,
    EvidencePackageCatalogResult,
    EvidencePicosQuestion,
    EvidenceQualityGate,
    EvidenceSourceDocumentSummary,
)

from .evidence_package_adapters import (
    CRSWNP_MASTER_ROOT,
    CRSWNP_ROOT,
    DEFAULT_EVIDENCE_PACKAGES,
    EVIDENCE_PACKAGE_IDS_BY_PROJECT,
    PNH_COMPETITOR_DB,
    CrswnpCsvEvidenceAdapter,
    EvidenceDesignPackageConfig,
    EvidencePackageAdapter,
    EvidencePackageAdapterError,
    PnhSqliteEvidenceAdapter,
)


class EvidenceDesignManifestService:
    def __init__(self, packages: Optional[List[EvidenceDesignPackageConfig]] = None):
        self.packages = packages or DEFAULT_EVIDENCE_PACKAGES
        self.adapters: Dict[str, EvidencePackageAdapter] = {}
        for config in self.packages:
            if config.adapter_type == "crswnp_csv":
                adapter = CrswnpCsvEvidenceAdapter(
                    config,
                    package_builder=lambda config=config: self._build_csv_package(config),
                )
            elif config.adapter_type == "pnh_sqlite":
                adapter = PnhSqliteEvidenceAdapter(config)
            else:
                raise ValueError(f"unsupported evidence adapter: {config.adapter_type}")
            self.adapters[config.package_id] = adapter

    def build_manifest(self, project_id: str) -> EvidenceDesignManifestResult:
        generated_at = datetime.now(timezone.utc)
        package_ids = EVIDENCE_PACKAGE_IDS_BY_PROJECT.get(project_id)
        if package_ids is None:
            raise KeyError(f"evidence_design not configured for project: {project_id}")
        package_summaries = [
            self.adapters[config.package_id].build_package()
            for config in self.packages
            if config.package_id in package_ids
        ]
        return EvidenceDesignManifestResult(
            project_id=project_id,
            generated_at=generated_at,
            package_count=len(package_summaries),
            total_products=sum(package.total_product_count or len(package.products) for package in package_summaries),
            total_trials=sum(package.total_trial_count or len(package.trial_designs) for package in package_summaries),
            total_documents=sum(package.total_document_count or len(package.documents) for package in package_summaries),
            total_result_rows=sum(
                package.total_result_count or len(package.efficacy_results) + len(package.safety_results)
                for package in package_summaries
            ),
            picos_question_count=sum(len(package.picos_questions) for package in package_summaries),
            quality_gate_count=sum(len(package.quality_gates) for package in package_summaries),
            packages=package_summaries,
            parser_notes=[
                "证据工作面从项目绑定的CSV或SQLite原始/近原始资料索引重建，不读取既有深度报告正文作为生产输入。",
                "Protocol、SAP、Publication和监管资料当前以文件级登记与结构化索引为主；正式章节级抽取需独立OCR/LLM服务后续接入。",
                "PICOS输出是待医学确认的设计问题队列，可流转到医学写作，但不代表方案已完成医学批准。",
            ],
        )

    def package_catalog(self, project_id: str) -> EvidencePackageCatalogResult:
        package_ids = EVIDENCE_PACKAGE_IDS_BY_PROJECT.get(project_id)
        if package_ids is None:
            raise KeyError(f"evidence_design not configured for project: {project_id}")
        return EvidencePackageCatalogResult(
            project_id=project_id,
            generated_at=datetime.now(timezone.utc),
            packages=[
                self.adapters[package_id].catalog_summary()
                for package_id in sorted(package_ids)
            ],
        )

    def candidate_page(
        self,
        project_id: str,
        package_id: str,
        *,
        candidate_type: str = "all",
        page: int = 1,
        page_size: int = 50,
        search: str = "",
    ) -> EvidenceCandidatePage:
        if page < 1:
            raise ValueError("page must be at least 1")
        if page_size < 1 or page_size > 200:
            raise ValueError("page_size must be between 1 and 200")
        adapter = self._adapter(project_id, package_id)
        result = adapter.candidate_page(
            candidate_type=candidate_type,
            page=page,
            page_size=page_size,
            search=search,
        )
        return result.model_copy(update={"project_id": project_id})

    def candidate_detail(
        self,
        project_id: str,
        package_id: str,
        evidence_id: str,
    ) -> EvidenceCandidateDetail:
        adapter = self._adapter(project_id, package_id)
        detail = adapter.candidate_detail(evidence_id)
        if detail.package_id != package_id:
            raise KeyError(f"evidence candidate not found: {evidence_id}")
        return detail.model_copy(update={"project_id": project_id})

    def package_hash(self, project_id: str, package_id: str) -> str:
        return self._adapter(project_id, package_id).source_hash()

    def _adapter(self, project_id: str, package_id: str) -> EvidencePackageAdapter:
        package_ids = EVIDENCE_PACKAGE_IDS_BY_PROJECT.get(project_id)
        if package_ids is None or package_id not in package_ids:
            raise KeyError(f"evidence package not found for project: {project_id}/{package_id}")
        adapter = self.adapters.get(package_id)
        if adapter is None:
            raise KeyError(f"evidence package adapter not found: {package_id}")
        return adapter

    def _build_csv_package(self, config: EvidenceDesignPackageConfig) -> EvidenceDesignPackageSummary:
        warnings: List[str] = []
        documents_df = _read_csv(config.master_root / "Document_Index.csv", warnings)
        trial_df = _read_csv(config.master_root / "Trial_Design.csv", warnings)
        efficacy_df = _read_csv(config.master_root / "Efficacy_Result.csv", warnings)
        safety_df = _read_csv(config.master_root / "Safety_Result.csv", warnings)

        documents = _build_documents(config, documents_df)
        trials = _build_trials(trial_df)
        efficacy_results = _build_result_rows(efficacy_df, result_kind="efficacy")
        safety_results = _build_result_rows(safety_df, result_kind="safety")
        products = _build_products(trial_df, documents_df)
        quality_gates = _build_quality_gates(config, documents_df, trial_df, efficacy_df, safety_df)
        picos_questions = _build_picos_questions(trial_df, efficacy_df, safety_df)

        return EvidenceDesignPackageSummary(
            package_id=config.package_id,
            package_label=config.package_label,
            indication=config.indication,
            source_root_label=config.source_root_label,
            package_role=config.package_role,
            total_product_count=len(products),
            total_trial_count=len(trials),
            total_document_count=len(documents),
            total_result_count=len(efficacy_results) + len(safety_results),
            candidate_count_by_type={
                "document": len(documents),
                "trial": len(trials),
                "efficacy": len(efficacy_results),
                "safety": len(safety_results),
            },
            products=products,
            trial_count_by_phase=dict(Counter(_cell(value) for value in trial_df.get("研究阶段", []) if _cell(value))),
            trial_count_by_status=dict(Counter(_cell(value) for value in trial_df.get("研究状态", []) if _cell(value))),
            document_count_by_type=dict(
                Counter(
                    _cell(value)
                    for value in documents_df.get(
                        "文件类型，Protocol/SAP/Publication/FDA Label/FDA Review/EMA EPAR/PMDA Review/NMPA Label/Company Disclosure",
                        [],
                    )
                    if _cell(value)
                )
            ),
            endpoint_count_by_name=dict(Counter(_cell(value) for value in efficacy_df.get("终点名称", []) if _cell(value))),
            safety_row_count=int(safety_df.shape[0]),
            documents=documents,
            trial_designs=trials,
            efficacy_results=efficacy_results,
            safety_results=safety_results,
            picos_questions=picos_questions,
            quality_gates=quality_gates,
            parser_warnings=warnings,
        )


def _read_csv(path: Path, warnings: List[str]) -> pd.DataFrame:
    if not path.exists():
        warnings.append(f"{path.name}不存在，无法生成证据清单。")
        return pd.DataFrame()
    try:
        return pd.read_csv(path, keep_default_na=False).fillna("")
    except Exception as exc:  # pragma: no cover - defensive for local encoding drift
        warnings.append(f"{path.name}读取失败：{exc}")
        return pd.DataFrame()


def _build_documents(config: EvidenceDesignPackageConfig, frame: pd.DataFrame) -> List[EvidenceSourceDocumentSummary]:
    documents: List[EvidenceSourceDocumentSummary] = []
    if frame.empty:
        return documents
    type_column = "文件类型，Protocol/SAP/Publication/FDA Label/FDA Review/EMA EPAR/PMDA Review/NMPA Label/Company Disclosure"
    for _, row in frame.iterrows():
        document_type = _cell(row.get(type_column))
        public_title = _public_title(_cell(row.get("文件标题")) or _cell(row.get("Primary_Source_Title")))
        file_path_text = _cell(row.get("文件路径"))
        file_format = Path(file_path_text).suffix.lower().lstrip(".").upper() if file_path_text else ""
        documents.append(
            EvidenceSourceDocumentSummary(
                document_id=_cell(row.get("Document_ID")) or f"{config.package_id}:doc:{len(documents) + 1}",
                document_type=document_type or "Source Document",
                public_title=public_title or "未命名资料",
                drug_name=_cell(row.get("药物名")),
                trial_identifier=_cell(row.get("研究编号")),
                source_package=config.package_id,
                relative_path=_relative_source_path(file_path_text, config.source_root),
                file_format=file_format,
                parser_status="indexed" if file_path_text else "metadata_only",
                primary_source_type=_cell(row.get("Primary_Source_Type")),
                primary_source_id=_cell(row.get("Primary_Source_ID")),
                primary_source_date=_cell(row.get("Primary_Source_Date")) or _cell(row.get("文件年份")),
                verification_status=_cell(row.get("Verification_Status")),
                evidence_level=_cell(row.get("Evidence_Level")),
                role_hint=_document_role_hint(document_type, public_title),
            )
        )
    return documents


def _build_trials(frame: pd.DataFrame) -> List[CompetitiveTrialDesignSummary]:
    trials: List[CompetitiveTrialDesignSummary] = []
    if frame.empty:
        return trials
    for _, row in frame.iterrows():
        trials.append(
            CompetitiveTrialDesignSummary(
                trial_id=_cell(row.get("Trial_ID")) or f"trial-{len(trials) + 1}",
                drug_name=_cell(row.get("药物名")),
                target=_cell(row.get("靶点")),
                sponsor=_cell(row.get("申办方")),
                registry=_cell(row.get("Registry")),
                registry_id=_cell(row.get("NCT / CTR / EudraCT / jRCT / 其他编号")),
                trial_acronym=_cell(row.get("研究简称")),
                phase=_cell(row.get("研究阶段")),
                trial_status=_cell(row.get("研究状态")),
                region=_cell(row.get("国家/地区")),
                design_type=" / ".join(
                    item
                    for item in [
                        _cell(row.get("随机/盲法/对照")),
                        _cell(row.get("研究设计类型")),
                    ]
                    if item
                ),
                sample_size=_cell(row.get("样本量")),
                treatment_group=_cell(row.get("治疗组")),
                comparator=_cell(row.get("对照组")),
                dose=_cell(row.get("剂量")),
                route=_cell(row.get("给药途径")),
                dosing_frequency=_cell(row.get("给药频率")),
                treatment_period=_cell(row.get("治疗期")),
                background_treatment=_cell(row.get("背景治疗要求")),
                key_population=_cell(row.get("关键纳入标准")) or _cell(row.get("基线疾病严重程度要求")),
                primary_endpoint=_cell(row.get("主要终点")),
                primary_timepoint=_cell(row.get("主要终点评价时间点")),
                key_secondary_endpoint=_cell(row.get("关键次要终点")),
                protocol_available=_cell(row.get("Protocol 是否可得")),
                sap_available=_cell(row.get("SAP 是否可得")),
                publication_available=_cell(row.get("Publication 是否可得")),
                verification_status=_cell(row.get("Verification_Status")),
                evidence_level=_cell(row.get("Evidence_Level")),
            )
        )
    return trials


def _build_result_rows(frame: pd.DataFrame, result_kind: str) -> List[CompetitiveResultEndpointSummary]:
    results: List[CompetitiveResultEndpointSummary] = []
    if frame.empty:
        return results
    for _, row in frame.iterrows():
        endpoint_name = _cell(row.get("终点名称")) or "安全性概览"
        effect_summary = _effect_summary(row, result_kind)
        results.append(
            CompetitiveResultEndpointSummary(
                result_id=_cell(row.get("Result_ID")) or _cell(row.get("Safety_ID")) or f"{result_kind}-{len(results) + 1}",
                result_kind=result_kind,
                trial_id=_cell(row.get("Trial_ID")),
                drug_name=_cell(row.get("药物名")),
                trial_identifier=_cell(row.get("研究编号")),
                endpoint_name=endpoint_name,
                endpoint_type=_cell(row.get("终点类型，primary/key secondary/secondary/exploratory")) or _cell(row.get("分析集")),
                timepoint=_cell(row.get("评价时间点")) or _cell(row.get("安全性观察周期")),
                treatment_group=_cell(row.get("治疗组")),
                comparator=_cell(row.get("对照组")),
                sample_size=_cell(row.get("N")),
                effect_summary=effect_summary,
                source_type=_cell(row.get("数据来源，publication/CT.gov/FDA review/EMA EPAR/company release")) or _cell(row.get("数据来源")),
                source_locator=_cell(row.get("页码/表号/图号")),
                verification_status=_cell(row.get("Verification_Status")),
                evidence_level=_cell(row.get("Evidence_Level")),
            )
        )
    return results


def _build_products(trial_df: pd.DataFrame, documents_df: pd.DataFrame) -> List[CompetitiveProductSummary]:
    if trial_df.empty:
        return []
    documents_by_drug = defaultdict(list)
    if not documents_df.empty:
        for _, row in documents_df.iterrows():
            drug = _cell(row.get("药物名"))
            if drug:
                documents_by_drug[drug].append(row)

    products: List[CompetitiveProductSummary] = []
    for drug_name, group in trial_df.groupby("药物名", dropna=False):
        drug = _cell(drug_name)
        if not drug:
            continue
        phases = Counter(_cell(value) for value in group.get("研究阶段", []) if _cell(value))
        regions = Counter(_region_bucket(_cell(value)) for value in group.get("国家/地区", []) if _cell(value))
        evidence_levels = [_cell(value) for value in group.get("Evidence_Level", []) if _cell(value)]
        approval_hint = _approval_hint(documents_by_drug.get(drug, []))
        products.append(
            CompetitiveProductSummary(
                product_id=f"product:{_stable_token(drug)}",
                drug_name=drug,
                target=_most_common(group.get("靶点", [])),
                sponsor=_most_common(group.get("申办方", [])),
                trial_count=int(group.shape[0]),
                phase_summary=dict(phases),
                region_summary=dict(regions),
                highest_evidence_level=sorted(evidence_levels)[0] if evidence_levels else "",
                approval_status_hint=approval_hint,
            )
        )
    return sorted(products, key=lambda item: (-item.trial_count, item.drug_name.lower()))


def _build_quality_gates(
    config: EvidenceDesignPackageConfig,
    documents_df: pd.DataFrame,
    trial_df: pd.DataFrame,
    efficacy_df: pd.DataFrame,
    safety_df: pd.DataFrame,
) -> List[EvidenceQualityGate]:
    doc_types = Counter(
        _cell(value)
        for value in documents_df.get(
            "文件类型，Protocol/SAP/Publication/FDA Label/FDA Review/EMA EPAR/PMDA Review/NMPA Label/Company Disclosure",
            [],
        )
        if _cell(value)
    )
    protocol_available = Counter(_cell(value) for value in trial_df.get("Protocol 是否可得", []) if _cell(value))
    sap_available = Counter(_cell(value) for value in trial_df.get("SAP 是否可得", []) if _cell(value))
    endpoint_names = Counter(_cell(value) for value in efficacy_df.get("终点名称", []) if _cell(value))
    timepoints = Counter(_cell(value) for value in efficacy_df.get("评价时间点", []) if _cell(value))
    gates = [
        EvidenceQualityGate(
            gate_id=f"{config.package_id}:gate:source_boundary",
            gate_label="来源边界已锁定",
            status="ok",
            owner="医学经理",
            detail="P0仅使用主数据库CSV、原文索引和公开注册/文献快照；既有深度报告/HTML只允许作QA参考，不作为生产输入。",
            source_refs=["Document_Index.csv", "Trial_Design.csv", "Efficacy_Result.csv", "Safety_Result.csv"],
        ),
        EvidenceQualityGate(
            gate_id=f"{config.package_id}:gate:full_text_parser",
            gate_label="Protocol/SAP全文抽取待接入",
            status="warning",
            owner="医学经理+独立AI服务",
            detail=f"已登记Protocol {doc_types.get('Protocol', 0)}个、SAP {doc_types.get('SAP', 0)}个；当前只进入文件级和结构化索引，章节级抽取需OCR/LLM链路。",
            source_refs=["03_Protocols", "04_SAP", "Document_Index.csv"],
        ),
        EvidenceQualityGate(
            gate_id=f"{config.package_id}:gate:protocol_sap_coverage",
            gate_label="竞品方案可得性待补齐",
            status="warning",
            owner="医学经理",
            detail=f"Trial_Design中Protocol可得性：{dict(protocol_available)}；SAP可得性：{dict(sap_available)}。不可得或待补项目不能直接进入最终PICOS判定。",
            source_refs=["Trial_Design.csv"],
        ),
        EvidenceQualityGate(
            gate_id=f"{config.package_id}:gate:cross_trial_comparability",
            gate_label="跨试验可比性需医学确认",
            status="warning",
            owner="医学经理/医学总监",
            detail=f"疗效结果覆盖{len(endpoint_names)}类终点和{len(timepoints)}类时间点，NPS/NCS/SNOT-22等需按评价时间点、人群和统计方法分层比较。",
            source_refs=["Efficacy_Result.csv", "Safety_Result.csv"],
        ),
        EvidenceQualityGate(
            gate_id=f"{config.package_id}:gate:efficacy_csv_field_alignment",
            gate_label="疗效结果字段语义需复核",
            status="warning",
            owner="医学经理+数据管理员",
            detail="P0将Efficacy_Result作为证据摘要表使用；部分来源/核验字段存在混合格式，暂不支持自动数值图、跨试验排名或优选判断。",
            source_refs=["Efficacy_Result.csv"],
        ),
        EvidenceQualityGate(
            gate_id=f"{config.package_id}:gate:online_refresh",
            gate_label="公开数据库在线刷新待配置",
            status="warning",
            owner="系统管理员",
            detail="当前使用本地ClinicalTrials.gov/PubMed/公司披露快照；后续需接入ClinicalTrials.gov v2、PubMed E-utilities、openFDA/CDE等在线刷新。",
            source_refs=["registry_snapshots", "pubmed_snapshots", "FDA_Label"],
        ),
        EvidenceQualityGate(
            gate_id=f"{config.package_id}:gate:picos_handoff",
            gate_label="PICOS输出需医学批准",
            status="blocked",
            owner="医学经理/医学总监",
            detail="系统只能形成待医学批准的正式内容草案；PICOS关键选择进入医学写作前必须由用户确认。",
            source_refs=["PICOS decision queue"],
        ),
    ]
    return gates


def _build_picos_questions(
    trial_df: pd.DataFrame,
    efficacy_df: pd.DataFrame,
    safety_df: pd.DataFrame,
) -> List[EvidencePicosQuestion]:
    trial_count = int(trial_df.shape[0])
    phase_counts = Counter(_cell(value) for value in trial_df.get("研究阶段", []) if _cell(value))
    endpoint_counts = Counter(_cell(value) for value in efficacy_df.get("终点名称", []) if _cell(value))
    safety_count = int(safety_df.shape[0])
    primary_endpoint_examples = ", ".join(endpoint for endpoint, _ in endpoint_counts.most_common(4)) or "待补充"
    return [
        EvidencePicosQuestion(
            question_id="picos:population",
            picos_domain="P - 研究人群",
            question="目标研究应纳入何种CRSwNP严重程度、既往手术/系统性激素使用史、合并哮喘或Type 2炎症特征人群？",
            evidence_status="evidence_available_needs_medical_decision",
            current_evidence_summary=f"Trial_Design已覆盖{trial_count}项竞品研究，关键纳入标准、NPS/NCS、嗅觉、既往手术和合并哮喘字段可用于对齐。",
            required_user_decision="由医学确认目标适应症人群、入排标准强度和中国/全球人群桥接策略。",
            source_refs=["Trial_Design.csv:关键纳入标准", "Trial_Design.csv:基线疾病严重程度要求"],
        ),
        EvidencePicosQuestion(
            question_id="picos:intervention",
            picos_domain="I - 干预措施",
            question="候选药物的剂量、给药途径、给药频率、治疗期和背景INCS要求应如何设定？",
            evidence_status="evidence_available_needs_medical_decision",
            current_evidence_summary=f"竞品阶段分布为{dict(phase_counts)}；治疗组、剂量、给药频率和背景治疗要求字段已登记。",
            required_user_decision="由医学确认目标剂量方案、治疗周期、背景治疗控制和救援治疗规则。",
            source_refs=["Trial_Design.csv:治疗组", "Trial_Design.csv:剂量", "Trial_Design.csv:背景治疗要求"],
        ),
        EvidencePicosQuestion(
            question_id="picos:comparator",
            picos_domain="C - 对照",
            question="对照组应采用安慰剂、标准治疗背景下安慰剂，还是需要活性对照/剂量对照？",
            evidence_status="evidence_available_needs_medical_decision",
            current_evidence_summary="Trial_Design显示多数关键研究采用随机、双盲、安慰剂对照和平行分组设计。",
            required_user_decision="由医学确认对照形式、随机比例、分层因素和盲法可行性。",
            source_refs=["Trial_Design.csv:随机/盲法/对照", "Trial_Design.csv:对照组"],
        ),
        EvidencePicosQuestion(
            question_id="picos:outcomes",
            picos_domain="O - 终点",
            question="主要终点和关键次要终点是否采用NPS/NCS、SNOT-22、嗅觉、手术/系统性激素需求等组合？",
            evidence_status="evidence_available_needs_medical_decision",
            current_evidence_summary=f"Efficacy_Result覆盖{len(endpoint_counts)}类终点，常见终点包括{primary_endpoint_examples}；Safety_Result登记{_safety_count_text(safety_count)}条安全性结果。",
            required_user_decision="由医学确认主要终点、关键次要终点、评价时间点、多重性控制和临床意义阈值。",
            source_refs=["Efficacy_Result.csv:终点名称", "Efficacy_Result.csv:评价时间点", "Safety_Result.csv"],
        ),
        EvidencePicosQuestion(
            question_id="picos:study_design",
            picos_domain="S - 研究设计",
            question="研究阶段、样本量、随机比例、随访期、extension/rollover和统计方法应如何与竞品和监管预期对齐？",
            evidence_status="needs_full_text_and_medical_decision",
            current_evidence_summary="Trial_Design已登记研究阶段、样本量、随机比例、治疗期、随访期和统计方法简述，但SAP/Protocol全文解析尚未完成。",
            required_user_decision="由医学确认研究定位、样本量估计输入、统计分析总体原则和监管沟通策略。",
            source_refs=["Trial_Design.csv:样本量", "Trial_Design.csv:统计学方法简述", "Document_Index.csv:Protocol/SAP"],
        ),
    ]


def _safety_count_text(count: int) -> str:
    return str(count)


def _effect_summary(row, result_kind: str) -> str:
    if result_kind == "safety":
        pieces = [
            f"TEAE {_cell(row.get('TEAE 百分比'))}" if _cell(row.get("TEAE 百分比")) else "",
            f"SAE {_cell(row.get('SAE 百分比'))}" if _cell(row.get("SAE 百分比")) else "",
            _cell(row.get("安全性结论")),
        ]
        return "；".join(piece for piece in pieces if piece) or _cell(row.get("Notes"))
    pieces = [
        _cell(row.get("placebo-adjusted difference")),
        _cell(row.get("LS mean difference")),
        _cell(row.get("OR/RR/HR，如适用")),
        _cell(row.get("95% CI")),
        _cell(row.get("p 值")),
    ]
    return "；".join(piece for piece in pieces if piece) or _cell(row.get("变化值")) or _cell(row.get("Notes"))


def _document_role_hint(document_type: str, title: str) -> str:
    text = f"{document_type} {title}".lower()
    if "protocol" in text:
        return "方案设计原文"
    if "sap" in text:
        return "统计分析计划原文"
    if "label" in text or "review" in text or "epar" in text:
        return "监管证据"
    if "publication" in text or "supplement" in text:
        return "发表证据"
    if "disclosure" in text:
        return "公司披露"
    return "证据资料"


def _approval_hint(rows: List[pd.Series]) -> str:
    text = " ".join(_cell(row.get("文件标题")) for row in rows)
    for token in ["NMPA已获批", "FDA已获批", "EMA已获批", "PMDA已获批"]:
        if token in text:
            return token
    if rows:
        return "已登记来源待核对"
    return "待补充"


def _relative_source_path(path_text: str, root: Path) -> str:
    if not path_text:
        return ""
    path = Path(path_text)
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def _public_title(title: str) -> str:
    return title.replace("/Users/smkzw/Documents/康哲项目资料/竞品调研/CRSwNP/", "").strip()


def _region_bucket(value: str) -> str:
    if not value:
        return ""
    if value == "China" or "China" in value:
        return "含中国"
    if "Global" in value or "多国" in value or "," in value:
        return "全球/多区域"
    return value[:24]


def _most_common(values) -> str:
    counter = Counter(_cell(value) for value in values if _cell(value))
    return counter.most_common(1)[0][0] if counter else ""


def _cell(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "nat"}:
        return ""
    return text


def _stable_token(text: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in text).strip("_")[:48] or "unknown"
