from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

from .user_project_store import UserProjectRecord, UserProjectStore


MEDICAL_MODULE_LABELS: Mapping[str, str] = {
    "dashboard": "项目总看板",
    "evidence_design": "证据调研与方案设计",
    "eligibility_review": "入排审核",
    "medical_monitoring": "医学监查",
    "data_analysis_tfl": "数据分析与TFL",
    "medical_writing": "医学写作",
    "safety_pv": "安全信号与PV协同",
    "approvals": "审批中心",
}


@dataclass(frozen=True)
class ProjectHeader:
    project_id: str
    project_code: str
    project_name: str
    indication: str
    product_name: str
    study_phase: str
    protocol_id: str
    protocol_version: str
    protocol_date: str
    status: str = "active"

    def public_dict(self) -> Dict[str, str]:
        return {
            "project_id": self.project_id,
            "project_code": self.project_code,
            "project_name": self.project_name,
            "indication": self.indication,
            "product_name": self.product_name,
            "study_phase": self.study_phase,
            "protocol_id": self.protocol_id,
            "protocol_version": self.protocol_version,
            "protocol_date": self.protocol_date,
            "status": self.status,
        }


@dataclass(frozen=True)
class ProjectSourceRef:
    source_id: str
    source_role: str
    module_keys: List[str]
    source_kind: str
    public_title: str
    source_scope: str = "real_raw_source"
    boundary_label: str = ""
    current_version: str = ""
    parser_status: str = "not_started"
    notes: List[str] = field(default_factory=list)
    internal_path: Optional[Path] = None

    @property
    def exists(self) -> bool:
        return self.internal_path.exists() if self.internal_path is not None else True

    def public_dict(self) -> Dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_role": self.source_role,
            "module_keys": list(self.module_keys),
            "source_kind": self.source_kind,
            "public_title": self.public_title,
            "source_scope": self.source_scope,
            "boundary_label": self.boundary_label,
            "current_version": self.current_version,
            "parser_status": self.parser_status,
            "availability": "available" if self.exists else "missing",
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ModuleSourceBinding:
    module: str
    label: str
    route_project_id: str
    primary_source_ids: List[str] = field(default_factory=list)
    supplemental_source_ids: List[str] = field(default_factory=list)
    display_batch_label: str = ""
    display_extract_date: str = ""
    ai_task_types: List[str] = field(default_factory=list)
    ai_capabilities: List[str] = field(default_factory=list)
    implementation_status: str = "planned"
    notes: List[str] = field(default_factory=list)

    def public_dict(self) -> Dict[str, object]:
        return {
            "module": self.module,
            "label": self.label,
            "route_project_id": self.route_project_id,
            "primary_source_ids": list(self.primary_source_ids),
            "supplemental_source_ids": list(self.supplemental_source_ids),
            "display_batch": {
                "batch_label": self.display_batch_label,
                "extract_date": self.display_extract_date,
            },
            "ai_task_types": list(self.ai_task_types),
            "ai_capabilities": list(self.ai_capabilities),
            "implementation_status": self.implementation_status,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ProjectSourceManifest:
    project_id: str
    aliases: List[str]
    source_mode: str
    header_project: ProjectHeader
    modules: List[ModuleSourceBinding]
    sources: List[ProjectSourceRef]

    def module_binding(self, module: str) -> ModuleSourceBinding:
        for binding in self.modules:
            if binding.module == module:
                return binding
        raise KeyError(f"module not configured for project source manifest: {self.project_id}/{module}")

    def public_dict(self) -> Dict[str, object]:
        return {
            "project_id": self.project_id,
            "aliases": list(self.aliases),
            "source_mode": self.source_mode,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "header_project": self.header_project.public_dict(),
            "modules": [binding.public_dict() for binding in self.modules],
            "route_bindings": {
                binding.module: binding.public_dict()
                for binding in self.modules
            },
            "sources": [source.public_dict() for source in self.sources],
        }

    def public_project_dict(self) -> Dict[str, object]:
        project = self.header_project.public_dict()
        project.update(
            {
                "aliases": list(self.aliases),
                "source_mode": self.source_mode,
                "modules": [
                    {
                        "module": binding.module,
                        "label": binding.label,
                        "route_project_id": binding.route_project_id,
                        "implementation_status": binding.implementation_status,
                    }
                    for binding in self.modules
                ],
            }
        )
        return project


def _project_root() -> Path:
    return Path(__file__).resolve().parents[5]


class ProjectSourceManifestService:
    def __init__(
        self,
        project_root: Optional[Path] = None,
        user_project_store: Optional[UserProjectStore] = None,
        include_reference_projects: bool = True,
    ):
        if not isinstance(include_reference_projects, bool):
            raise TypeError("include_reference_projects must be a bool")
        self.project_root = project_root or _project_root()
        self.user_project_store = user_project_store
        self.include_reference_projects = include_reference_projects
        self._canonical_builders = {
            "proj_rux_03_002": self._rux_manifest,
            "proj_d001": self._d001_manifest,
            "proj_my009_uc": self._my009_manifest,
            "proj_my008_pnh_3_01": self._my008_pnh_manifest,
            "proj_my008_pnh_3_02": self._my008_pnh_3_02_manifest,
            "proj_mgk10_sar_real": self._mgk10_sar_real_manifest,
            "proj_mgk10_crswnp": self._mgk10_crswnp_manifest,
            "proj_mgk10_sar_demo": self._mgk10_demo_manifest,
            "proj_ra_greenfield_sandbox": self._ra_greenfield_sandbox_manifest,
        }
        self._aliases = {
            "proj_mgk10_sar_demo": "proj_mgk10_sar_demo",
            "proj_mgk10_crswnp": "proj_mgk10_crswnp",
            "proj_rux_03_002": "proj_rux_03_002",
            "rux_03_002_monitoring_raw": "proj_rux_03_002",
            "proj_d001": "proj_d001",
            "d001_raw_intake": "proj_d001",
            "proj_d001_raw_intake": "proj_d001",
            "proj_my009_uc": "proj_my009_uc",
            "my009_uc": "proj_my009_uc",
            "my009_uc_raw_intake": "proj_my009_uc",
            "my009_uc_monitoring_raw": "proj_my009_uc",
            "proj_my008_pnh_3_01": "proj_my008_pnh_3_01",
            "my008_pnh_3_01": "proj_my008_pnh_3_01",
            "proj_my008_pnh_3_02": "proj_my008_pnh_3_02",
            "my008_pnh_3_02": "proj_my008_pnh_3_02",
            "proj_mgk10_sar_real": "proj_mgk10_sar_real",
            "proj_ra_greenfield_sandbox": "proj_ra_greenfield_sandbox",
        }

    @staticmethod
    def parse_include_reference_projects(value: Optional[str]) -> bool:
        if value is None:
            return True
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
        raise ValueError(
            "WORKBENCH_INCLUDE_REFERENCE_PROJECTS must be 'true' or 'false'"
        )

    def canonical_project_ids(self) -> tuple[str, ...]:
        return tuple(self._canonical_builders)

    def canonical_project_id(self, project_id: str) -> str:
        canonical_id = self._aliases.get(project_id)
        if (
            canonical_id is None
            and self.user_project_store is not None
            and self.user_project_store.get(project_id) is not None
        ):
            canonical_id = project_id
        if canonical_id is None:
            raise KeyError(project_id)
        return canonical_id

    def is_user_created_project(self, project_id: str) -> bool:
        """Return whether a project is owned by the writing workspace store.

        User-created greenfield projects do not expose any legacy medical-
        monitoring route.  The distinction is kept here so the API boundary
        can allow the writing shell to read its own manifest without weakening
        fail-closed authorization for canonical monitoring projects.
        """

        try:
            canonical_id = self.canonical_project_id(project_id)
        except KeyError:
            return False
        return bool(self.user_project_store and self.user_project_store.get(canonical_id))

    def build_manifest(self, project_id: str) -> ProjectSourceManifest:
        canonical_id = self.canonical_project_id(project_id)
        builder = self._canonical_builders.get(canonical_id)
        if builder is not None:
            return builder()
        record = self.user_project_store.get(canonical_id) if self.user_project_store else None
        if record is None:
            raise KeyError(project_id)
        return self._user_project_manifest(record)

    def list_public_projects(self) -> List[Dict[str, object]]:
        projects = []
        if self.include_reference_projects:
            projects.extend(
                self._canonical_builders[project_id]().public_project_dict()
                for project_id in self.canonical_project_ids()
            )
        if self.user_project_store:
            projects.extend(
                self._user_project_manifest(record).public_project_dict()
                for record in self.user_project_store.records()
            )
        return projects

    def public_manifest(self, project_id: str) -> Dict[str, object]:
        return self.build_manifest(project_id).public_dict()

    def module_binding(self, project_id: str, module: str) -> ModuleSourceBinding:
        return self.build_manifest(project_id).module_binding(module)

    def _binding(
        self,
        module: str,
        route_project_id: str,
        primary: Iterable[str] = (),
        supplemental: Iterable[str] = (),
        display_batch_label: str = "",
        display_extract_date: str = "",
        ai_task_types: Iterable[str] = (),
        ai_capabilities: Iterable[str] = (),
        implementation_status: str = "planned",
        notes: Iterable[str] = (),
    ) -> ModuleSourceBinding:
        return ModuleSourceBinding(
            module=module,
            label=MEDICAL_MODULE_LABELS[module],
            route_project_id=route_project_id,
            primary_source_ids=list(primary),
            supplemental_source_ids=list(supplemental),
            display_batch_label=display_batch_label,
            display_extract_date=display_extract_date,
            ai_task_types=list(ai_task_types),
            ai_capabilities=list(ai_capabilities),
            implementation_status=implementation_status,
            notes=list(notes),
        )

    def _user_project_manifest(self, record: UserProjectRecord) -> ProjectSourceManifest:
        project_id = record.project_id
        return ProjectSourceManifest(
            project_id=project_id,
            aliases=[project_id],
            source_mode=f"user_created_{record.entry_mode}",
            header_project=ProjectHeader(
                project_id=project_id,
                project_code=record.project_code,
                project_name=record.project_name,
                indication=record.indication,
                product_name=record.product_name,
                study_phase=record.study_phase,
                protocol_id=record.protocol_id,
                protocol_version=record.protocol_version,
                protocol_date=record.protocol_date,
                status=record.status,
            ),
            modules=[
                self._binding(
                    "dashboard",
                    project_id,
                    implementation_status="authoring_ready",
                    notes=["用户创建的医学写作项目。"],
                ),
                self._binding(
                    "medical_writing",
                    project_id,
                    implementation_status="authoring_ready",
                    ai_task_types=["protocol_authoring", "competitor_protocol_search"],
                    ai_capabilities=["independent_llm", "clinicaltrials_gov"],
                ),
                self._binding(
                    "approvals",
                    project_id,
                    implementation_status="authoring_ready",
                ),
            ],
            sources=[],
        )

    def _ra_greenfield_sandbox_manifest(self) -> ProjectSourceManifest:
        project_id = "proj_ra_greenfield_sandbox"
        return ProjectSourceManifest(
            project_id=project_id,
            aliases=[project_id],
            source_mode="greenfield_sandbox",
            header_project=ProjectHeader(
                project_id=project_id,
                project_code="RA-GREENFIELD",
                project_name="类风湿关节炎从零方案写作沙盒",
                indication="类风湿关节炎",
                product_name="待定义试验药物",
                study_phase="",
                protocol_id="RA-GREENFIELD-DRAFT",
                protocol_version="-",
                protocol_date="",
            ),
            modules=[
                self._binding(
                    "dashboard",
                    project_id,
                    implementation_status="greenfield_ready",
                    notes=["仅用于从零医学写作全链路测试，不预置方案正文或研究设计结论。"],
                ),
                self._binding(
                    "medical_writing",
                    project_id,
                    implementation_status="greenfield_ready",
                    ai_task_types=["protocol_authoring", "competitor_protocol_search"],
                    ai_capabilities=["independent_llm", "clinicaltrials_gov"],
                    notes=["从研究框架和PICOS开始，不绑定任何既有方案或生成结果。"],
                ),
                self._binding(
                    "approvals",
                    project_id,
                    implementation_status="planned",
                    notes=["后续承接章节、表格、量表和全文医学批准。"],
                ),
            ],
            sources=[],
        )

    def _mgk10_demo_manifest(self) -> ProjectSourceManifest:
        project_id = "proj_mgk10_sar_demo"
        sources = [
            ProjectSourceRef(
                source_id="mgk10_demo_repository",
                source_role="demo_repository",
                module_keys=list(MEDICAL_MODULE_LABELS),
                source_kind="demo_json",
                public_title="MG-K10 SAR 工作台演示数据仓",
                source_scope="demo_seed",
                parser_status="parsed",
                internal_path=self.project_root / "demo_data" / "workbench_demo_v0_1.json",
            ),
            ProjectSourceRef(
                source_id="mgk10_legacy_eligibility_adapter",
                source_role="legacy_eligibility_adapter",
                module_keys=["eligibility_review"],
                source_kind="legacy_adapter",
                public_title="MG-K10 SAR 入排审核 legacy adapter",
                source_scope="legacy_workflow",
                parser_status="available",
                notes=["用于演示和对照，不作为其他真实项目的原始资料输入。"],
            ),
        ]
        return ProjectSourceManifest(
            project_id=project_id,
            aliases=[project_id],
            source_mode="demo_and_legacy",
            header_project=ProjectHeader(
                project_id=project_id,
                project_code="MG-K10-SAR-DEMO",
                project_name="MG-K10 SAR 医学经理工作台演示项目",
                indication="季节性过敏性鼻炎",
                product_name="MG-K10",
                study_phase="III",
                protocol_id="MG-K10-SAR-III",
                protocol_version="V2.1",
                protocol_date="2026-06-01",
            ),
            modules=[
                self._binding("dashboard", project_id, ["mgk10_demo_repository"], display_batch_label="原始数据 listing Batch 003", display_extract_date="2026-06-28", implementation_status="demo_available"),
                self._binding("evidence_design", project_id, ["mgk10_demo_repository"], display_batch_label="MG-K10 demo evidence pack", display_extract_date="2026-06-28", implementation_status="demo_available"),
                self._binding("eligibility_review", project_id, ["mgk10_legacy_eligibility_adapter"], display_batch_label="MG-K10 legacy 入排对照", display_extract_date="2026-06-28", implementation_status="legacy_available"),
                self._binding("medical_monitoring", project_id, ["mgk10_demo_repository"], display_batch_label="原始数据 listing Batch 003", display_extract_date="2026-06-28", implementation_status="demo_available"),
                self._binding("data_analysis_tfl", project_id, ["mgk10_demo_repository"], display_batch_label="MG-K10 demo TFL pack", display_extract_date="2026-06-28", implementation_status="demo_available"),
                self._binding("medical_writing", project_id, ["mgk10_demo_repository"], display_batch_label="MG-K10 demo writing pack", display_extract_date="2026-06-28", implementation_status="demo_available"),
                self._binding("safety_pv", project_id, ["mgk10_demo_repository"], display_batch_label="MG-K10 demo safety pack", display_extract_date="2026-06-28", implementation_status="demo_available"),
                self._binding("approvals", project_id, ["mgk10_demo_repository"], display_batch_label="MG-K10 demo approval queue", display_extract_date="2026-06-28", implementation_status="demo_available"),
            ],
            sources=sources,
        )

    def _rux_manifest(self) -> ProjectSourceManifest:
        project_id = "proj_rux_03_002"
        rux_base = Path("/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD")
        sources = [
            ProjectSourceRef(
                source_id="rux_listing_20250612",
                source_role="monitoring_listing",
                module_keys=["medical_monitoring", "data_analysis_tfl", "safety_pv"],
                source_kind="local_file_excel",
                public_title="RUX-03-002 列表数据集 Excel 2025-06-12",
                current_version="2025-06-12",
                parser_status="parsed_raw_intake",
                internal_path=rux_base / "CFDI Inspection" / "准备阶段" / "RUX-03-002_列表_数据集_Excel_20250612_处理后.xlsx",
            ),
            ProjectSourceRef(
                source_id="rux_subject_report_20250613",
                source_role="monitoring_subject_report",
                module_keys=["medical_monitoring"],
                source_kind="local_file_excel",
                public_title="RUX-03-002 受试者报表 2025-06-13",
                current_version="2025-06-13",
                parser_status="queued",
                internal_path=rux_base / "CFDI Inspection" / "准备阶段" / "RUX-03-002_受试者报表_20250613.xls",
            ),
            ProjectSourceRef(
                source_id="rux_protocol_v1_3",
                source_role="protocol_docx",
                module_keys=["medical_monitoring", "data_analysis_tfl", "medical_writing"],
                source_kind="local_file_docx",
                public_title="RUX-03-002 临床研究方案 V1.3",
                current_version="V1.3 / 2024-08-14",
                parser_status="parsed_raw_intake",
                internal_path=(
                    rux_base
                    / "CFDI Inspection"
                    / "RUX-03-002-自查文件包-20260107"
                    / "10-临床试验重要文件"
                    / "1-临床试验方案"
                    / "V1.3版-2024.8.14"
                    / "磷酸芦可替尼乳膏-AD3期临床研究方案V1.3-clean-20240814.docx"
                ),
            ),
            ProjectSourceRef(
                source_id="rux_cm_domain",
                source_role="concomitant_medication_domain",
                module_keys=["medical_monitoring", "safety_pv"],
                source_kind="derived_listing_domain",
                public_title="CM/CM1 非试验用合并用药 domain",
                source_scope="derived_from_monitoring_listing",
                boundary_label="非试验用合并用药",
                parser_status="parsed_raw_intake",
            ),
            ProjectSourceRef(
                source_id="rux_study_drug_change_domain",
                source_role="study_drug_change_domain",
                module_keys=["medical_monitoring"],
                source_kind="derived_listing_domain",
                public_title="ECB/ECA/DA/EX 试验药物给药、暂停、重启、剂量调整 domain",
                source_scope="derived_from_monitoring_listing",
                boundary_label="试验药物变更/剂量调整",
                parser_status="parsed_raw_intake",
            ),
            ProjectSourceRef(
                source_id="rux_sdtm_package",
                source_role="sdtm_package",
                module_keys=["data_analysis_tfl"],
                source_kind="local_directory",
                public_title="RUX-03-002 SDTM package inventory",
                parser_status="inventory_available",
                internal_path=rux_base / "DM&SA" / "国内外共4项研究数据库" / "rux-03-002" / "tabulations" / "sdtm",
            ),
            ProjectSourceRef(
                source_id="rux_final_tfl_package",
                source_role="tfl_output_package",
                module_keys=["data_analysis_tfl", "medical_writing"],
                source_kind="local_directory",
                public_title="RUX-03-002 SAR/TFL 输出包",
                parser_status="inventory_available",
                internal_path=rux_base / "2-RUX-03-002-现场核查项目层面文件目录-20260424" / "38.SAR&TFLs",
            ),
            ProjectSourceRef(
                source_id="rux_pv_plan_package",
                source_role="pv_plan_package",
                module_keys=["safety_pv"],
                source_kind="local_directory",
                public_title="RUX-03-002 PV 计划包",
                parser_status="inventory_available",
                internal_path=rux_base / "2-RUX-03-002-现场核查项目层面文件目录-20260424" / "22.PV计划",
            ),
        ]
        return ProjectSourceManifest(
            project_id=project_id,
            aliases=[project_id, "rux_03_002_monitoring_raw"],
            source_mode="real_project",
            header_project=ProjectHeader(
                project_id=project_id,
                project_code="RUX-03-002",
                project_name="磷酸芦可替尼乳膏 RUX-03-002",
                indication="特应性皮炎",
                product_name="磷酸芦可替尼乳膏",
                study_phase="III",
                protocol_id="RUX-03-002",
                protocol_version="V1.3",
                protocol_date="2024-08-14",
            ),
            modules=[
                self._binding("dashboard", project_id, ["rux_listing_20250612", "rux_protocol_v1_3"], display_batch_label="RUX listing 2025-06-12", display_extract_date="2025-06-12", implementation_status="real_source_slice"),
                self._binding(
                    "medical_monitoring",
                    project_id,
                    ["rux_listing_20250612", "rux_protocol_v1_3"],
                    ["rux_subject_report_20250613", "rux_cm_domain", "rux_study_drug_change_domain"],
                    "RUX listing 2025-06-12",
                    "2025-06-12",
                    ["listing_semantic_mapping", "protocol_rule_extraction", "monitoring_risk_interpretation", "subject_timeline_derivation", "patient_profile_derivation"],
                    ["llm:deepseek-v4-pro", "ocr:glm-ocr-bf16|paddleocr-vl-1.6", "vlm:minimax-m3"],
                    "real_source_slice",
                ),
                self._binding("data_analysis_tfl", project_id, ["rux_sdtm_package", "rux_final_tfl_package"], ["rux_listing_20250612"], "RUX SDTM/TFL 包", "2025-06-12", implementation_status="source_inventory_slice"),
                self._binding("medical_writing", project_id, ["rux_protocol_v1_3", "rux_final_tfl_package"], display_batch_label="RUX 方案 V1.3 + SAR/TFL", display_extract_date="2024-08-14", ai_task_types=["medical_writing_revision"], ai_capabilities=["llm:deepseek-v4-pro"], implementation_status="source_inventory_slice"),
                self._binding("safety_pv", project_id, ["rux_listing_20250612", "rux_pv_plan_package"], ["rux_cm_domain"], "RUX PV/Listing 包", "2025-06-12", implementation_status="source_inventory_slice"),
                self._binding("approvals", project_id, ["rux_listing_20250612"], display_batch_label="RUX 医学处置审批队列", display_extract_date="2025-06-12", implementation_status="real_source_slice"),
            ],
            sources=sources,
        )

    def _mgk10_crswnp_manifest(self) -> ProjectSourceManifest:
        project_id = "proj_mgk10_crswnp"
        project_base = Path("/Users/smkzw/Documents/康哲项目资料/MG-K10/CRSwNP")
        evidence_base = Path("/Users/smkzw/Documents/康哲项目资料/竞品调研/CRSwNP")
        sources = [
            ProjectSourceRef(
                source_id="mgk10_crswnp_protocol_v1_0",
                source_role="protocol_docx",
                module_keys=["evidence_design", "eligibility_review", "medical_writing"],
                source_kind="local_file_docx",
                public_title="MG-K10 CRSwNP III期临床试验方案 V1.0",
                current_version="V1.0 / 2026-03-18",
                parser_status="source_registered",
                internal_path=project_base / "试验文件" / "试验方案" / "MG-K10-CRSwNP_临床试验方案-III期-V1.0-2026.03.18-clean.docx",
            ),
            ProjectSourceRef(
                source_id="crswnp_competitive_evidence_root",
                source_role="competitive_evidence_package",
                module_keys=["evidence_design"],
                source_kind="local_directory",
                public_title="CRSwNP竞品调研原始资料与主数据库",
                parser_status="parsed_source_index",
                internal_path=evidence_base,
            ),
        ]
        return ProjectSourceManifest(
            project_id=project_id,
            aliases=[project_id],
            source_mode="real_project",
            header_project=ProjectHeader(
                project_id=project_id,
                project_code="MG-K10-CRSwNP",
                project_name="MG-K10 慢性鼻窦炎伴鼻息肉 III期临床研究",
                indication="慢性鼻窦炎伴鼻息肉",
                product_name="MG-K10",
                study_phase="III",
                protocol_id="MG-K10-CRSwNP",
                protocol_version="V1.0",
                protocol_date="2026-03-18",
            ),
            modules=[
                self._binding("dashboard", project_id, ["mgk10_crswnp_protocol_v1_0"], display_batch_label="MG-K10 CRSwNP方案 V1.0", display_extract_date="2026-03-18", implementation_status="source_manifest_only"),
                self._binding("evidence_design", project_id, ["crswnp_competitive_evidence_root", "mgk10_crswnp_protocol_v1_0"], display_batch_label="CRSwNP竞品证据主数据库", display_extract_date="2026-07-03", implementation_status="real_source_slice"),
                self._binding("eligibility_review", project_id, ["mgk10_crswnp_protocol_v1_0"], display_batch_label="MG-K10 CRSwNP方案 V1.0", display_extract_date="2026-03-18", implementation_status="source_manifest_only"),
                self._binding("medical_writing", project_id, ["mgk10_crswnp_protocol_v1_0"], display_batch_label="MG-K10 CRSwNP方案 V1.0", display_extract_date="2026-03-18", implementation_status="source_manifest_only"),
                self._binding("approvals", project_id, ["mgk10_crswnp_protocol_v1_0"], display_batch_label="MG-K10 CRSwNP审批队列", display_extract_date="2026-03-18", implementation_status="planned"),
            ],
            sources=sources,
        )

    def _d001_manifest(self) -> ProjectSourceManifest:
        project_id = "proj_d001"
        d001_base = Path("/Users/smkzw/Documents/康哲项目资料/AI/入排/test-D001项目")
        sources = [
            ProjectSourceRef(
                source_id="d001_protocol_v1_0",
                source_role="eligibility_protocol_docx",
                module_keys=["eligibility_review", "medical_writing"],
                source_kind="local_file_docx",
                public_title="CMS-D001 银屑病 2/3 期临床方案 V1.0",
                current_version="V1.0 / 2025-12-21",
                parser_status="parsed_raw_intake",
                internal_path=d001_base / "CMS-D001 银屑病2、3期临床方案 v1.0-2025.12.21.docx",
            ),
            ProjectSourceRef(
                source_id="d001_raw_subject_bundle",
                source_role="eligibility_raw_subject_bundle",
                module_keys=["eligibility_review"],
                source_kind="local_directory",
                public_title="CMS-D001 全量入组原始资料包",
                parser_status="parsed_raw_intake_pending_ocr_vlm",
                internal_path=d001_base / "全量-入组",
            ),
            ProjectSourceRef(
                source_id="d001_legacy_enrollment_review_app",
                source_role="legacy_eligibility_adapter",
                module_keys=["eligibility_review"],
                source_kind="legacy_app",
                public_title="既有入排审核系统对照结果",
                source_scope="legacy_comparison",
                parser_status="available_for_comparison",
                notes=["只能用于 UI/逻辑对照和迁移验证，不能代替原始方案与原始受试者资料。"],
                internal_path=Path("/Users/smkzw/Documents/康哲项目资料/AI/入排/enrollment-review-app"),
            ),
        ]
        return ProjectSourceManifest(
            project_id=project_id,
            aliases=[project_id, "d001_raw_intake", "proj_d001_raw_intake"],
            source_mode="real_project",
            header_project=ProjectHeader(
                project_id=project_id,
                project_code="CMS-D001",
                project_name="CMS-D001 银屑病 2/3 期临床研究",
                indication="银屑病",
                product_name="CMS-D001",
                study_phase="II/III",
                protocol_id="CMS-D001",
                protocol_version="V1.0",
                protocol_date="2025-12-21",
            ),
            modules=[
                self._binding("dashboard", project_id, ["d001_protocol_v1_0"], display_batch_label="D001 方案 V1.0", display_extract_date="2025-12-21", implementation_status="source_manifest_only"),
                self._binding(
                    "eligibility_review",
                    "d001_raw_intake",
                    ["d001_protocol_v1_0", "d001_raw_subject_bundle"],
                    ["d001_legacy_enrollment_review_app"],
                    "D001 全量入组资料",
                    "2025-12-21",
                    ["protocol_rule_extraction", "eligibility_rule_review"],
                    ["llm:deepseek-v4-pro", "ocr:glm-ocr-bf16|paddleocr-vl-1.6", "vlm:minimax-m3"],
                    "real_source_slice",
                ),
                self._binding("medical_writing", project_id, ["d001_protocol_v1_0"], display_batch_label="D001 方案 V1.0", display_extract_date="2025-12-21", ai_task_types=["medical_writing_revision"], ai_capabilities=["llm:deepseek-v4-pro"], implementation_status="source_inventory_slice"),
                self._binding("approvals", project_id, ["d001_protocol_v1_0"], display_batch_label="D001 审批占位", display_extract_date="2025-12-21", implementation_status="planned"),
            ],
            sources=sources,
        )

    def _my009_manifest(self) -> ProjectSourceManifest:
        project_id = "proj_my009_uc"
        my009_base = Path("/Users/smkzw/Documents/朗来项目资料/MY009治疗UC")
        sources = [
            ProjectSourceRef(
                source_id="my009_protocol_v3_0",
                source_role="protocol_docx",
                module_keys=["eligibility_review", "medical_monitoring", "medical_writing"],
                source_kind="local_file_docx",
                public_title="MY009 UC IIa 期临床研究方案 V3.0",
                current_version="V3.0 / 2025-09-26",
                parser_status="parsed_raw_intake",
                internal_path=my009_base / "方案及配套资料" / "3.0" / "MY009-UC-Ⅱa期-临床研究方案-V3.0 20250926-clean (1).docx",
            ),
            ProjectSourceRef(
                source_id="my009_evf_subject_bundle",
                source_role="eligibility_raw_subject_bundle",
                module_keys=["eligibility_review"],
                source_kind="local_directory",
                public_title="MY009 UC EVF 审核原始资料包",
                parser_status="parsed_raw_intake_pending_ocr_vlm",
                internal_path=my009_base / "EVF审核",
            ),
            ProjectSourceRef(
                source_id="my009_mm_listing_20260408",
                source_role="monitoring_listing",
                module_keys=["medical_monitoring", "safety_pv"],
                source_kind="local_file_excel",
                public_title="MY009 UC MM Listing 2026-04-08",
                current_version="2026-04-08",
                parser_status="parsed_raw_intake",
                internal_path=my009_base / "S1安全性评价-202604" / "MY009-UC-2-01-MM Listing_20260408(已自动还原).xlsx",
            ),
            ProjectSourceRef(
                source_id="my009_cm_domain",
                source_role="concomitant_medication_domain",
                module_keys=["medical_monitoring", "safety_pv"],
                source_kind="derived_listing_domain",
                public_title="MY009 CM 非试验用合并用药 domain",
                source_scope="derived_from_monitoring_listing",
                boundary_label="非试验用合并用药",
                parser_status="parsed_raw_intake",
            ),
            ProjectSourceRef(
                source_id="my009_study_drug_change_domain",
                source_role="study_drug_change_domain",
                module_keys=["medical_monitoring"],
                source_kind="derived_listing_domain",
                public_title="MY009 DA/EX 试验药物给药、暂停、重启、剂量调整 domain",
                source_scope="derived_from_monitoring_listing",
                boundary_label="试验药物变更/剂量调整",
                parser_status="parsed_raw_intake",
            ),
            ProjectSourceRef(
                source_id="my009_safety_package_202604",
                source_role="safety_pv_package",
                module_keys=["safety_pv"],
                source_kind="local_directory",
                public_title="MY009 UC S1 安全性评价资料包",
                parser_status="inventory_available",
                internal_path=my009_base / "S1安全性评价-202604",
            ),
            ProjectSourceRef(
                source_id="my009_dsur4_source",
                source_role="dsur_source",
                module_keys=["safety_pv", "medical_writing"],
                source_kind="local_file_docx",
                public_title="MY009 DSUR #4 资料收集包",
                parser_status="inventory_available",
                internal_path=my009_base / "DSUR" / "附件1：MY009_DSUR#4_资料收集 to CPM、RA、医学-MM.docx",
            ),
        ]
        return ProjectSourceManifest(
            project_id=project_id,
            aliases=[project_id, "my009_uc", "my009_uc_raw_intake", "my009_uc_monitoring_raw"],
            source_mode="real_project",
            header_project=ProjectHeader(
                project_id=project_id,
                project_code="MY009-UC",
                project_name="MY009 溃疡性结肠炎 IIa 期临床研究",
                indication="溃疡性结肠炎",
                product_name="MY009",
                study_phase="IIa",
                protocol_id="MY009-UC",
                protocol_version="V3.0",
                protocol_date="2025-09-26",
            ),
            modules=[
                self._binding("dashboard", project_id, ["my009_protocol_v3_0", "my009_mm_listing_20260408"], display_batch_label="MY009 MM Listing 2026-04-08", display_extract_date="2026-04-08", implementation_status="source_manifest_only"),
                self._binding(
                    "eligibility_review",
                    "my009_uc_raw_intake",
                    ["my009_protocol_v3_0", "my009_evf_subject_bundle"],
                    (),
                    "MY009 EVF 审核资料",
                    "2025-09-26",
                    ai_task_types=["protocol_rule_extraction", "eligibility_rule_review"],
                    ai_capabilities=["llm:deepseek-v4-pro", "ocr:glm-ocr-bf16|paddleocr-vl-1.6", "vlm:minimax-m3"],
                    implementation_status="real_source_slice",
                ),
                self._binding(
                    "medical_monitoring",
                    "my009_uc_monitoring_raw",
                    ["my009_mm_listing_20260408", "my009_protocol_v3_0"],
                    ["my009_cm_domain", "my009_study_drug_change_domain"],
                    "MY009 MM Listing 2026-04-08",
                    "2026-04-08",
                    ["listing_semantic_mapping", "protocol_rule_extraction", "monitoring_risk_interpretation"],
                    ["llm:deepseek-v4-pro", "ocr:glm-ocr-bf16|paddleocr-vl-1.6", "vlm:minimax-m3"],
                    "real_source_slice",
                ),
                self._binding("medical_writing", project_id, ["my009_protocol_v3_0", "my009_dsur4_source"], display_batch_label="MY009 方案 V3.0 + DSUR", display_extract_date="2025-09-26", ai_task_types=["medical_writing_revision"], ai_capabilities=["llm:deepseek-v4-pro"], implementation_status="source_inventory_slice"),
                self._binding("safety_pv", project_id, ["my009_mm_listing_20260408", "my009_safety_package_202604", "my009_dsur4_source"], ["my009_cm_domain"], "MY009 S1/PV 2026-04", "2026-04-08", implementation_status="source_inventory_slice"),
                self._binding("approvals", project_id, ["my009_protocol_v3_0"], display_batch_label="MY009 审批占位", display_extract_date="2025-09-26", implementation_status="planned"),
            ],
            sources=sources,
        )

    def _mgk10_sar_real_manifest(self) -> ProjectSourceManifest:
        project_id = "proj_mgk10_sar_real"
        mgk10_base = self.project_root.parent.parent / "MG-K10" / "SAR"
        listing_path = (
            mgk10_base
            / "13. CFDI核查"
            / "自查"
            / "评分SDV"
            / "【锁库后Data Listing】MG-K10-SAR-001_FormExcelAllVersion_202601201126.xlsx"
        )
        protocol_path = (
            mgk10_base
            / "4. Protocol"
            / "MG-K10-SAR-001_临床研究方案_ V2.1_20250919_clean版 .docx"
        )
        sources = [
            ProjectSourceRef(
                source_id="mgk10_sar_listing_20260120",
                source_role="monitoring_listing",
                module_keys=["medical_monitoring"],
                source_kind="local_file_excel",
                public_title="MG-K10-SAR 锁库后 Data Listing 2026-01-20",
                current_version="2026-01-20",
                parser_status="parsed_raw_intake",
                internal_path=listing_path,
            ),
            ProjectSourceRef(
                source_id="mgk10_sar_protocol_v2_1",
                source_role="protocol_docx",
                module_keys=["medical_monitoring"],
                source_kind="local_file_docx",
                public_title="MG-K10-SAR 临床研究方案 V2.1",
                current_version="V2.1 / 2025-09-19",
                parser_status="parsed_raw_intake",
                internal_path=protocol_path,
            ),
            ProjectSourceRef(
                source_id="mgk10_sar_cm_domain",
                source_role="concomitant_medication_domain",
                module_keys=["medical_monitoring"],
                source_kind="derived_listing_domain",
                public_title="MG-K10-SAR CM 非试验用药 domain",
                source_scope="derived_from_monitoring_listing",
                boundary_label="非试验用药",
                parser_status="parsed_raw_intake",
            ),
            ProjectSourceRef(
                source_id="mgk10_sar_blinded_ip_domain",
                source_role="study_drug_administration_domain",
                module_keys=["medical_monitoring"],
                source_kind="derived_listing_domain",
                public_title="MG-K10-SAR EX 盲态试验药物/安慰剂给药 domain",
                source_scope="derived_from_monitoring_listing",
                boundary_label="盲态试验药物/安慰剂",
                parser_status="parsed_raw_intake",
            ),
            ProjectSourceRef(
                source_id="mgk10_sar_background_treatment_domain",
                source_role="protocol_background_treatment_domain",
                module_keys=["medical_monitoring"],
                source_kind="derived_listing_domain",
                public_title="MG-K10-SAR EX1/2/4/5/7 方案背景治疗 domain",
                source_scope="derived_from_monitoring_listing",
                boundary_label="方案规定背景治疗",
                parser_status="parsed_raw_intake",
            ),
        ]
        return ProjectSourceManifest(
            project_id=project_id,
            aliases=[project_id],
            source_mode="real_project",
            header_project=ProjectHeader(
                project_id=project_id,
                project_code="MG-K10-SAR-001",
                project_name="MG-K10-SAR 季节性过敏性鼻炎临床研究",
                indication="季节性过敏性鼻炎",
                product_name="MG-K10",
                study_phase="II",
                protocol_id="MG-K10-SAR-001",
                protocol_version="V2.1",
                protocol_date="2025-09-19",
            ),
            modules=[
                self._binding(
                    "dashboard",
                    project_id,
                    ["mgk10_sar_listing_20260120", "mgk10_sar_protocol_v2_1"],
                    display_batch_label="MG-K10-SAR Listing 2026-01-20",
                    display_extract_date="2026-01-20",
                    implementation_status="real_source_slice",
                ),
                self._binding(
                    "medical_monitoring",
                    project_id,
                    ["mgk10_sar_listing_20260120", "mgk10_sar_protocol_v2_1"],
                    [
                        "mgk10_sar_cm_domain",
                        "mgk10_sar_blinded_ip_domain",
                        "mgk10_sar_background_treatment_domain",
                    ],
                    "MG-K10-SAR Listing 2026-01-20",
                    "2026-01-20",
                    ["listing_semantic_mapping", "protocol_rule_extraction", "monitoring_risk_interpretation"],
                    ["independent_ai:configured_runtime"],
                    "real_source_slice",
                ),
            ],
            sources=sources,
        )

    def _my008_pnh_3_02_manifest(self) -> ProjectSourceManifest:
        """Register the 3-02 source boundary without claiming an adapter.

        This project is intentionally source-manifest-only until its listing
        structure, protocol semantics, and monitoring adapter pass the
        independent-AI and runtime gates.  Keeping the binding limited to the
        dashboard and medical-monitoring surfaces prevents the source-only
        registration from silently activating medical-writing/TFL routes.
        """

        project_id = "proj_my008_pnh_3_02"
        project_base = Path("/Users/smkzw/Documents/朗来项目资料/MY008治疗PNH/3-02（MM外包）")
        protocol_path = (
            project_base
            / "方案"
            / "2.1版方案"
            / "MY008211A-PNH-3-02_研究方案_V2.1_2024.11.08-clean.docx"
        )
        listing_path = (
            project_base
            / "原始数据"
            / "【3-02初治锁库后数据集】MY008211A-PNH-3-02-锁库后EXCEL数据集.xlsx"
        )
        tfl_path = project_base / "TFL" / "定稿TFL"
        csr_path = project_base / "CSR" / "【CSR】MY008211A-PNH-3-02-CSR （最最终定稿-清洁版）.docx"
        source_only_notes = [
            "来源已登记；尚未解析listing结构或建立医学监查适配器。",
            "当前不得创建批次、风险快照或提交AI任务；需先通过独立AI与运行时门禁。",
        ]
        sources = [
            ProjectSourceRef(
                source_id="my008_pnh_3_02_locked_dataset",
                source_role="monitoring_locked_dataset",
                module_keys=["dashboard", "medical_monitoring"],
                source_kind="local_file_xlsx",
                public_title="MY008211A-PNH-3-02锁库后EXCEL数据集",
                source_scope="real_raw_source",
                boundary_label="锁库后总量基线",
                current_version="锁库后数据集",
                parser_status="source_registered",
                notes=source_only_notes,
                internal_path=listing_path,
            ),
            ProjectSourceRef(
                source_id="my008_pnh_3_02_protocol_v2_1",
                source_role="clinical_study_protocol",
                module_keys=["dashboard", "medical_monitoring"],
                source_kind="local_file_docx",
                public_title="MY008211A-PNH-3-02研究方案V2.1清洁版",
                source_scope="real_raw_source",
                boundary_label="研究方案",
                current_version="V2.1 / 2024-11-08",
                parser_status="source_registered",
                notes=source_only_notes,
                internal_path=protocol_path,
            ),
            ProjectSourceRef(
                source_id="my008_pnh_3_02_tfl_delivery",
                source_role="tfl_dataset_and_output_package",
                module_keys=["medical_monitoring"],
                source_kind="local_directory",
                public_title="MY008211A-PNH-3-02定稿TFL目录",
                source_scope="supporting_reference_source",
                boundary_label="TFL支持资料",
                parser_status="source_registered",
                notes=["仅登记目录；本切片不扫描或解析TFL内容。", *source_only_notes],
                internal_path=tfl_path,
            ),
            ProjectSourceRef(
                source_id="my008_pnh_3_02_csr",
                source_role="csr_docx",
                module_keys=["medical_monitoring"],
                source_kind="local_file_docx",
                public_title="MY008211A-PNH-3-02 CSR定稿清洁版",
                source_scope="supporting_reference_source",
                boundary_label="CSR支持资料",
                parser_status="source_registered",
                notes=["仅作为方案/数据核查的支持资料登记；不产生医学结论。", *source_only_notes],
                internal_path=csr_path,
            ),
        ]
        return ProjectSourceManifest(
            project_id=project_id,
            aliases=[project_id, "my008_pnh_3_02"],
            source_mode="real_project",
            header_project=ProjectHeader(
                project_id=project_id,
                project_code="MY008211A-PNH-3-02",
                project_name="MY008211A-PNH-3-02 阵发性睡眠性血红蛋白尿研究",
                indication="阵发性睡眠性血红蛋白尿",
                product_name="MY008211A",
                study_phase="III",
                protocol_id="MY008211A-PNH-3-02",
                protocol_version="V2.1",
                protocol_date="2024-11-08",
            ),
            modules=[
                self._binding(
                    "dashboard",
                    project_id,
                    ["my008_pnh_3_02_locked_dataset", "my008_pnh_3_02_protocol_v2_1"],
                    display_batch_label="MY008-3-02 锁库后数据集",
                    implementation_status="source_manifest_only",
                    notes=source_only_notes,
                ),
                self._binding(
                    "medical_monitoring",
                    project_id,
                    ["my008_pnh_3_02_locked_dataset", "my008_pnh_3_02_protocol_v2_1"],
                    ["my008_pnh_3_02_tfl_delivery", "my008_pnh_3_02_csr"],
                    display_batch_label="MY008-3-02 锁库后数据集",
                    ai_task_types=[
                        "listing_structure_discovery",
                        "protocol_rule_extraction",
                        "monitoring_risk_interpretation",
                    ],
                    implementation_status="source_manifest_only",
                    notes=source_only_notes,
                ),
            ],
            sources=sources,
        )

    def _my008_pnh_manifest(self) -> ProjectSourceManifest:
        project_id = "proj_my008_pnh_3_01"
        project_base = Path("/Users/smkzw/Documents/朗来项目资料/MY008治疗PNH/3-01（MM外包）")
        delivery_root = project_base / "SAP & TFL" / "2025-12-02 MY008211A-PNH-3-01 Final delivery"
        protocol_path = (
            project_base
            / "方案"
            / "V1.1方案"
            / "（缺含研究者签字页方案）MY008211A-PNH-3-01-V1.1-通用版-2024.11.24-clean"
            / "研究方案"
            / "MY008211A-PNH-3-01_研究方案_V1.1_2025.1.7clean.docx"
        )
        sources = [
            ProjectSourceRef(
                source_id="pnh_competitive_evidence_db",
                source_role="competitive_evidence_database",
                module_keys=["evidence_design"],
                source_kind="local_sqlite_readonly",
                public_title="PNH竞品调研规范化证据数据库",
                current_version="2026-07-10核验快照",
                parser_status="parsed_readonly_adapter",
                notes=["候选池从试验、发表和监管状态源表重建；空evidence_registry不代表无证据。"],
                internal_path=Path("/Users/smkzw/Documents/调研/PNH/03_extracted/pnh_competitor.sqlite"),
            ),
            ProjectSourceRef(
                source_id="my008_pnh_3_01_locked_dataset",
                source_role="monitoring_locked_dataset",
                module_keys=["dashboard", "medical_monitoring"],
                source_kind="local_file_xlsx",
                public_title="MY008211A-PNH-3-01锁库后原始数据集",
                source_scope="real_raw_source",
                boundary_label="锁库后总量基线",
                parser_status="source_registered",
                internal_path=project_base
                / "原始数据"
                / "【3-01经治锁库后原始数据】MY008211A-PNH-3-01_锁库后EXCEL数据集.xlsx",
            ),
            ProjectSourceRef(
                source_id="my008_pnh_protocol_v1_1",
                source_role="clinical_study_protocol",
                module_keys=["medical_monitoring", "medical_writing", "safety_pv"],
                source_kind="local_file_docx",
                public_title="MY008211A-PNH-3-01研究方案V1.1清洁版",
                current_version="V1.1 / 2025-01-07",
                parser_status="source_registered",
                internal_path=protocol_path,
            ),
            ProjectSourceRef(
                source_id="my008_pnh_tfl_delivery",
                source_role="tfl_dataset_and_output_package",
                module_keys=[
                    "medical_monitoring",
                    "data_analysis_tfl",
                    "medical_writing",
                    "safety_pv",
                ],
                source_kind="local_directory",
                public_title="MY008211A-PNH-3-01 SAP/TFL最终交付包",
                parser_status="inventory_available",
                internal_path=delivery_root,
            ),
            ProjectSourceRef(
                source_id="my008_pnh_csr",
                source_role="csr_docx",
                module_keys=["medical_monitoring", "medical_writing"],
                source_kind="local_file_docx",
                public_title="MY008211A-PNH-3-01 CSR定稿清洁版",
                parser_status="source_registered",
                internal_path=project_base / "CSR" / "MY008211A-PNH-3-01 CSR_定稿（清洁版）_20251226.docx",
            ),
            ProjectSourceRef(
                source_id="my008_pnh_safety_plan",
                source_role="safety_management_plan",
                module_keys=["safety_pv"],
                source_kind="local_file_docx",
                public_title="MY008211A-PNH-3-01安全管理计划",
                parser_status="source_registered",
                internal_path=project_base / "安全管理计划" / "MY008211A-PNH-3-01-安全管理计划 V0.1-0925.docx",
            ),
        ]
        return ProjectSourceManifest(
            project_id=project_id,
            aliases=[project_id, "my008_pnh_3_01"],
            source_mode="real_project",
            header_project=ProjectHeader(
                project_id=project_id,
                project_code="MY008211A-PNH-3-01",
                project_name="MY008211A-PNH-3-01 阵发性睡眠性血红蛋白尿研究",
                indication="阵发性睡眠性血红蛋白尿",
                product_name="MY008211A",
                study_phase="III",
                protocol_id="MY008211A-PNH-3-01",
                protocol_version="V1.1",
                protocol_date="2025-01-07",
            ),
            modules=[
                self._binding(
                    "dashboard",
                    project_id,
                    ["my008_pnh_3_01_locked_dataset", "my008_pnh_protocol_v1_1"],
                    display_batch_label="MY008-3-01 锁库后数据集",
                    display_extract_date="",
                    implementation_status="source_manifest_only",
                ),
                self._binding(
                    "medical_monitoring",
                    project_id,
                    ["my008_pnh_3_01_locked_dataset", "my008_pnh_protocol_v1_1"],
                    ["my008_pnh_tfl_delivery", "my008_pnh_csr"],
                    "MY008-3-01 锁库后数据集",
                    "",
                    [
                        "listing_structure_discovery",
                        "protocol_rule_extraction",
                        "monitoring_risk_interpretation",
                    ],
                    [],
                    "source_manifest_only",
                    [
                        "仅登记协议/listing/TFL/CSR来源；结构解析、字段映射、适配器和独立AI激活尚未完成。",
                    ],
                ),
                self._binding(
                    "evidence_design",
                    project_id,
                    ["pnh_competitive_evidence_db"],
                    display_batch_label="PNH竞品证据数据库",
                    display_extract_date="2026-07-10",
                    ai_task_types=["competitive_evidence_review", "picos_design_coach"],
                    ai_capabilities=["llm:deepseek-v4-pro", "vlm:minimax-m3"],
                    implementation_status="real_source_slice",
                ),
                self._binding("data_analysis_tfl", project_id, ["my008_pnh_tfl_delivery"], display_batch_label="MY008 PNH SAP/TFL最终交付包", display_extract_date="2025-12-02", implementation_status="real_source_slice"),
                self._binding("medical_writing", project_id, ["my008_pnh_protocol_v1_1", "my008_pnh_csr", "my008_pnh_tfl_delivery"], display_batch_label="MY008 PNH方案V1.1、CSR与TFL", display_extract_date="2025-12-26", ai_task_types=["medical_writing_revision"], ai_capabilities=["llm:deepseek-v4-pro"], implementation_status="real_source_slice"),
                self._binding("safety_pv", project_id, ["my008_pnh_protocol_v1_1", "my008_pnh_safety_plan", "my008_pnh_tfl_delivery"], display_batch_label="MY008 PNH安全资料", display_extract_date="2025-12-02", implementation_status="source_manifest_only"),
                self._binding("approvals", project_id, ["my008_pnh_tfl_delivery"], display_batch_label="MY008 PNH审批队列", display_extract_date="2025-12-02", implementation_status="planned"),
            ],
            sources=sources,
        )
