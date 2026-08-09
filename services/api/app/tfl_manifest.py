from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

import pandas as pd

from packages.contracts.workbench_contracts import (
    ClinicalDatasetSummary,
    TflManifestResult,
    TflOutputSummary,
    TflPackageSummary,
)


RUX_DATASET_ROOT = Path("/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/DM&SA/国内外共4项研究数据库/rux-03-002")
RUX_TFL_SINGLE_ROOT = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/2-RUX-03-002-现场核查项目层面文件目录-20260424/38.SAR&TFLs/32.2-TFL/RUX-03-002_Final Run Delivery_2025-07-17/03 TLF Report/Single"
)
MY008_ROOT = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY008治疗PNH/3-01（MM外包）/SAP & TFL/2025-12-02 MY008211A-PNH-3-01 Final delivery"
)


@dataclass(frozen=True)
class TflPackageConfig:
    package_id: str
    package_label: str
    dataset_root: Path
    tfl_root: Path
    dataset_root_label: str
    tfl_root_label: str
    expected_study_ids: tuple[str, ...] = ()
    sap_version: str = ""
    project_ids: tuple[str, ...] = ()


DEFAULT_PACKAGES = [
    TflPackageConfig(
        package_id="rux_03_002",
        package_label="RUX-03-002 ADaM/SDTM 与 SAR/TFL交付包",
        dataset_root=RUX_DATASET_ROOT,
        tfl_root=RUX_TFL_SINGLE_ROOT,
        dataset_root_label="RUX-03-002 ADaM/SDTM递交数据包",
        tfl_root_label="RUX-03-002 Final Run Single TFL输出",
        expected_study_ids=("RUX-03-002",),
        project_ids=("proj_rux_03_002",),
    ),
    TflPackageConfig(
        package_id="my008_pnh_3_01",
        package_label="MY008211A-PNH-3-01 SAP/TFL最终交付包",
        dataset_root=MY008_ROOT,
        tfl_root=MY008_ROOT / "tlf",
        dataset_root_label="MY008 ADaM/SDTM与TFL数据交付目录",
        tfl_root_label="MY008 TFL RTF输出目录",
        expected_study_ids=("MY008211A-PNH-3-01",),
        project_ids=("proj_my008_pnh_3_01",),
    ),
]

TFL_PACKAGE_IDS_BY_PROJECT = {
    "proj_rux_03_002": {"rux_03_002"},
    "proj_my008_pnh_3_01": {"my008_pnh_3_01"},
}


class TflManifestService:
    def __init__(
        self,
        packages: Optional[List[TflPackageConfig]] = None,
        package_ids_by_project: Optional[Mapping[str, set[str]]] = None,
    ):
        self.packages = DEFAULT_PACKAGES if packages is None else packages
        if package_ids_by_project is not None:
            self.package_ids_by_project = {key: set(value) for key, value in package_ids_by_project.items()}
        else:
            derived = {
                project_id: {config.package_id for config in self.packages if project_id in config.project_ids}
                for project_id in {item for config in self.packages for item in config.project_ids}
            }
            self.package_ids_by_project = derived or {
                key: set(value) for key, value in TFL_PACKAGE_IDS_BY_PROJECT.items()
            }
        self._manifest_cache: Dict[str, TflManifestResult] = {}

    def build_manifest(self, project_id: str, force_refresh: bool = False) -> TflManifestResult:
        if not force_refresh and project_id in self._manifest_cache:
            return self._manifest_cache[project_id]
        package_ids = self.package_ids_by_project.get(project_id)
        if package_ids is None:
            raise KeyError(f"data_analysis_tfl not configured for project: {project_id}")
        generated_at = datetime.now(timezone.utc)
        package_summaries = [
            self._build_package(project_id, config, generated_at)
            for config in self.packages
            if config.package_id in package_ids
        ]
        if not package_summaries:
            raise KeyError(f"data_analysis_tfl package mapping is empty for project: {project_id}")
        parser_notes = [
            "XPT数据集使用pandas.read_sas读取行数、变量数和变量名；SAS7BDAT在当前运行环境缺少pyreadstat时仅做交付清单登记。",
            "P0仅展示数据集、define.xml和TFL交付物的可追溯清单，不生成正式监管TFL。",
        ]
        manifest = TflManifestResult(
            project_id=project_id,
            generated_at=generated_at,
            package_count=len(package_summaries),
            total_datasets=sum(len(package.datasets) for package in package_summaries),
            total_outputs=sum(len(package.outputs) for package in package_summaries),
            packages=package_summaries,
            parser_notes=parser_notes,
        )
        self._manifest_cache[project_id] = manifest
        return manifest

    def _build_package(self, project_id: str, config: TflPackageConfig, generated_at: datetime) -> TflPackageSummary:
        parser_warnings: List[str] = []
        define_index, define_itemgroup_count = _parse_define_index(config.dataset_root, parser_warnings)
        datasets = _scan_datasets(
            config.package_id,
            config.dataset_root,
            define_index,
            parser_warnings,
            expected_study_ids=config.expected_study_ids,
        )
        outputs = _scan_tfl_outputs(config.package_id, config.tfl_root, datasets, parser_warnings)
        dataset_counts = Counter(dataset.standard for dataset in datasets)
        role_counts = Counter(dataset.package_role for dataset in datasets)
        format_counts = Counter(dataset.file_format for dataset in datasets)
        output_counts = Counter(output.output_type for output in outputs)
        traceability_notes = [
            "优先用define.xml建立数据集标签、结构和类别；缺失define.xml时仅按目录和文件名推断。",
            "RTF/PDF输出按TFL编号归一化后与同编号SAS7BDAT交付数据文件配对。",
            "正式TFL生成仍需SAP、TFL shell、统计程序和独立AI/统计运行时进一步校验。",
        ]
        content_validation_status, content_validation_notes = _package_content_validation(
            datasets,
            config.expected_study_ids,
            config.sap_version,
        )
        return TflPackageSummary(
            package_id=config.package_id,
            package_label=config.package_label,
            project_id=project_id,
            generated_at=generated_at,
            dataset_root_label=config.dataset_root_label,
            tfl_root_label=config.tfl_root_label,
            define_xml_count=len(list(config.dataset_root.rglob("define.xml"))) if config.dataset_root.exists() else 0,
            define_itemgroup_count=define_itemgroup_count,
            dataset_count_by_standard=dict(dataset_counts),
            dataset_count_by_role=dict(role_counts),
            dataset_count_by_format=dict(format_counts),
            tfl_count_by_type=dict(output_counts),
            datasets=datasets,
            outputs=outputs,
            traceability_notes=traceability_notes,
            parser_warnings=parser_warnings,
            content_validation_status=content_validation_status,
            content_validation_notes=content_validation_notes,
            expected_sap_version=config.sap_version,
            sap_version_status="bound" if config.sap_version else "warning",
        )


def _parse_define_index(root: Path, parser_warnings: List[str]) -> tuple[Dict[str, Dict[str, str]], int]:
    index: Dict[str, Dict[str, str]] = {}
    if not root.exists():
        parser_warnings.append(f"{root.name}目录不存在，无法解析define.xml。")
        return index, 0

    itemgroup_count = 0
    for define_file in root.rglob("define.xml"):
        try:
            document = ET.parse(define_file)
        except ET.ParseError as exc:
            parser_warnings.append(f"{define_file.name}解析失败：{exc}")
            continue
        source = _safe_relative(define_file, root)
        for element in document.getroot().iter():
            if _local_name(element.tag) != "ItemGroupDef":
                continue
            itemgroup_count += 1
            name = element.attrib.get("SASDatasetName") or element.attrib.get("Name") or ""
            if not name:
                continue
            description = ""
            for child in element.iter():
                if _local_name(child.tag) == "TranslatedText" and child.text:
                    description = child.text.strip()
                    break
            index[name.upper()] = {
                "dataset_name": name.upper(),
                "domain": element.attrib.get("Domain", ""),
                "label": description,
                "purpose": element.attrib.get("Purpose", ""),
                "structure": _attribute_by_local_name(element.attrib, "Structure"),
                "class_name": _attribute_by_local_name(element.attrib, "Class"),
                "define_source": source,
            }
    if itemgroup_count == 0:
        parser_warnings.append("未发现define.xml ItemGroupDef；数据集与define对齐状态为缺失。")
    return index, itemgroup_count


def _scan_datasets(
    package_id: str,
    dataset_root: Path,
    define_index: Dict[str, Dict[str, str]],
    parser_warnings: List[str],
    expected_study_ids: tuple[str, ...] = (),
) -> List[ClinicalDatasetSummary]:
    if not dataset_root.exists():
        parser_warnings.append(f"{dataset_root.name}目录不存在，无法生成数据集清单。")
        return []

    dataset_files = sorted(
        [path for path in dataset_root.rglob("*") if path.suffix.lower() in {".xpt", ".sas7bdat"} and path.is_file()],
        key=lambda item: str(item).lower(),
    )
    datasets: List[ClinicalDatasetSummary] = []
    for file_path in dataset_files:
        dataset_name = file_path.stem.upper()
        standard = _standard_from_path(file_path, dataset_root)
        package_role = _package_role_from_path(file_path, dataset_root)
        define_meta = define_index.get(dataset_name, {})
        parser_status = "inventory_only_sas7bdat_requires_pyreadstat" if file_path.suffix.lower() == ".sas7bdat" else "pending"
        row_count = None
        column_count = None
        sample_variables: List[str] = []
        observed_study_ids: List[str] = []
        study_identity_status = "not_assessed"
        observed_domain_values: List[str] = []
        domain_consistency_status = "not_assessed"
        content_validation_notes: List[str] = []

        if file_path.suffix.lower() == ".xpt":
            try:
                frame = pd.read_sas(file_path, format="xport", encoding="utf-8")
                row_count = int(frame.shape[0])
                column_count = int(frame.shape[1])
                sample_variables = [str(column) for column in list(frame.columns)[:18]]
                parser_status = "parsed"
                observed_study_ids = _distinct_text_values(frame, "STUDYID")
                study_identity_status = _identity_status(
                    observed_study_ids,
                    expected_study_ids,
                )
                if study_identity_status == "warning":
                    content_validation_notes.append("未发现STUDYID，需在交付前确认研究标识。")
                elif study_identity_status == "mismatch":
                    content_validation_notes.append("STUDYID与当前项目不一致。")
                domain_column, expected_domain = _domain_check_context(
                    standard,
                    dataset_name,
                    define_meta.get("domain", ""),
                )
                observed_domain_values = _distinct_text_values(frame, domain_column) if domain_column else []
                domain_consistency_status = _domain_status(standard, observed_domain_values, expected_domain)
                if domain_consistency_status == "warning":
                    content_validation_notes.append(f"SDTM数据集未发现{domain_column or '适用domain'}值，需确认domain归属。")
                elif domain_consistency_status == "mismatch":
                    content_validation_notes.append("DOMAIN值与define/数据集名称推断不一致。")
            except Exception as exc:  # pragma: no cover - defensive for vendor-specific XPT variants
                parser_status = "parse_failed"
                parser_warnings.append(f"{_safe_relative(file_path, dataset_root)}读取失败：{exc}")

        datasets.append(
            ClinicalDatasetSummary(
                dataset_id=f"{package_id}:dataset:{dataset_name.lower()}:{_stable_path_token(file_path, dataset_root)}",
                dataset_name=dataset_name,
                standard=standard,
                package_role=package_role,
                domain=define_meta.get("domain") or _domain_from_dataset_name(dataset_name),
                label=define_meta.get("label", ""),
                class_name=define_meta.get("class_name", ""),
                purpose=define_meta.get("purpose", ""),
                structure=define_meta.get("structure", ""),
                source_package=package_id,
                relative_path=_safe_relative(file_path, dataset_root),
                file_format=file_path.suffix.lower().lstrip(".").upper(),
                parser_status=parser_status,
                row_count=row_count,
                column_count=column_count,
                key_variables=_key_variables(sample_variables),
                sample_variables=sample_variables,
                define_linked=bool(define_meta),
                define_source=define_meta.get("define_source", ""),
                size_bytes=file_path.stat().st_size,
                observed_study_ids=observed_study_ids,
                study_identity_status=study_identity_status,
                observed_domain_values=observed_domain_values,
                domain_consistency_status=domain_consistency_status,
                content_validation_notes=content_validation_notes,
            )
        )
    return datasets


def _distinct_text_values(frame: pd.DataFrame, column: str) -> List[str]:
    column_by_upper = {str(item).upper(): item for item in frame.columns}
    source_column = column_by_upper.get(column.upper())
    if source_column is None:
        return []
    values = []
    for value in frame[source_column].dropna().unique():
        text = str(value).strip()
        if text and text not in values:
            values.append(text)
    return sorted(values)


def _identity_status(observed: List[str], expected: tuple[str, ...]) -> str:
    if not expected:
        return "not_assessed"
    if not observed:
        return "warning"
    expected_normalized = {_normal_identity(value) for value in expected}
    observed_normalized = {_normal_identity(value) for value in observed}
    return "match" if observed_normalized <= expected_normalized else "mismatch"


def _domain_status(standard: str, observed: List[str], expected: str) -> str:
    if standard != "SDTM":
        return "not_applicable"
    if not expected:
        return "not_applicable"
    if not observed:
        return "warning"
    expected_normalized = _normal_identity(expected)
    observed_normalized = {_normal_identity(value) for value in observed}
    return "match" if observed_normalized == {expected_normalized} else "mismatch"


def _domain_check_context(standard: str, dataset_name: str, define_domain: str) -> tuple[str, str]:
    if standard != "SDTM":
        return "", ""
    upper = dataset_name.upper()
    if upper.startswith("SUPP") and len(upper) > 4:
        return "RDOMAIN", upper[4:]
    if upper == "RELREC":
        return "", ""
    return "DOMAIN", define_domain or _domain_from_dataset_name(upper)


def _package_content_validation(
    datasets: List[ClinicalDatasetSummary],
    expected_study_ids: tuple[str, ...],
    sap_version: str,
) -> tuple[str, List[str]]:
    notes: List[str] = []
    identity_statuses = {dataset.study_identity_status for dataset in datasets}
    domain_statuses = {
        dataset.domain_consistency_status
        for dataset in datasets
        if dataset.standard == "SDTM"
    }
    if any(dataset.parser_status == "parse_failed" for dataset in datasets):
        notes.append("存在无法解析的数据集，内容级研究标识或domain尚未核验。")
    if "mismatch" in identity_statuses or "mismatch" in domain_statuses:
        status = "mismatch"
        notes.append("至少一个数据集的STUDYID或DOMAIN与当前交付上下文不一致。")
    elif (
        not expected_study_ids
        or "warning" in identity_statuses
        or "not_assessed" in identity_statuses
        or "warning" in domain_statuses
        or "not_assessed" in domain_statuses
        or any(dataset.parser_status != "parsed" for dataset in datasets)
        or not sap_version
    ):
        status = "warning"
        notes.append("研究标识、适用DOMAIN、数据集解析或SAP版本至少一项仍待确认。")
    elif datasets and "match" in identity_statuses:
        status = "matched"
        notes.append("已解析数据集的STUDYID及适用的SDTM DOMAIN与当前交付上下文一致。")
    else:
        status = "not_assessed"
        notes.append("当前无可执行内容一致性核验的数据集。")
    if expected_study_ids:
        notes.append(f"预期研究标识：{' / '.join(expected_study_ids)}。")
    notes.append(f"SAP版本上下文：{sap_version}。" if sap_version else "SAP版本尚未绑定，正式交付前需确认。")
    return status, notes


def _normal_identity(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _scan_tfl_outputs(
    package_id: str,
    tfl_root: Path,
    datasets: List[ClinicalDatasetSummary],
    parser_warnings: List[str],
) -> List[TflOutputSummary]:
    if not tfl_root.exists():
        parser_warnings.append(f"{tfl_root.name}目录不存在，无法生成TFL输出清单。")
        return []

    paired_dataset_by_key = {
        _normal_pair_key(Path(dataset.relative_path).stem): dataset.dataset_id
        for dataset in datasets
        if dataset.file_format == "SAS7BDAT"
    }
    output_files = sorted(
        [path for path in tfl_root.rglob("*") if path.suffix.lower() == ".rtf" and path.is_file()],
        key=lambda item: str(item).lower(),
    )
    outputs: List[TflOutputSummary] = []
    for file_path in output_files:
        normalized_key = _normal_pair_key(file_path.stem)
        output_type = _output_type_from_path(file_path)
        display_id = _display_id(file_path.stem, output_type)
        outputs.append(
            TflOutputSummary(
                output_id=f"{package_id}:tfl:{normalized_key}:{_stable_path_token(file_path, tfl_root)}",
                display_id=display_id,
                output_type=output_type,
                domain_hint=_domain_hint(file_path.stem),
                title_hint=_title_hint(file_path.stem),
                source_package=package_id,
                relative_path=_safe_relative(file_path, tfl_root),
                file_format=file_path.suffix.lower().lstrip(".").upper(),
                parser_status="inventory_only",
                paired_file_id=paired_dataset_by_key.get(normalized_key),
                size_bytes=file_path.stat().st_size,
            )
        )
    return outputs


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _attribute_by_local_name(attributes: Dict[str, str], name: str) -> str:
    for key, value in attributes.items():
        if _local_name(key) == name:
            return value
    return ""


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def _stable_path_token(path: Path, root: Path) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _safe_relative(path, root).lower()).strip("_")[:80]


def _relative_parts(path: Path, root: Optional[Path]) -> set[str]:
    relative = Path(_safe_relative(path, root)) if root is not None else path
    return {part.lower() for part in relative.parts[:-1]}


def _standard_from_path(path: Path, root: Optional[Path] = None) -> str:
    parts = _relative_parts(path, root)
    name = path.stem.lower()
    if "tfl datas" in parts or "tlf datas" in parts:
        return "TFL_DATA"
    if "sdtm" in parts or "tabulations" in parts:
        return "SDTM"
    if "adam" in parts:
        return "ADaM"
    if name.startswith("ad"):
        return "ADaM"
    return "DATA"


def _package_role_from_path(path: Path, root: Optional[Path] = None) -> str:
    parts = _relative_parts(path, root)
    suffix = path.suffix.lower().lstrip(".")
    if "tfl datas" in parts or "tlf datas" in parts:
        return f"tfl_data_{suffix}"
    if "raw" in parts:
        return f"raw_{suffix}"
    if "adam" in parts:
        return f"adam_{suffix}"
    if "sdtm" in parts or "tabulations" in parts:
        return f"sdtm_{suffix}"
    return f"data_{suffix}"


def _domain_from_dataset_name(name: str) -> str:
    upper = name.upper()
    if upper.startswith("AD") and len(upper) > 2:
        return upper[2:]
    return upper[:2]


def _key_variables(columns: Iterable[str]) -> List[str]:
    columns = [str(column) for column in columns]
    upper_by_original = {column.upper(): column for column in columns}
    priority = [
        "STUDYID",
        "USUBJID",
        "SUBJID",
        "SITEID",
        "TRT01P",
        "SAFFL",
        "FASFL",
        "PARAMCD",
        "PARAM",
        "AVAL",
        "AVALC",
        "VISIT",
        "VISITNUM",
        "ADT",
        "AEBODSYS",
        "AEDECOD",
        "LBTESTCD",
        "QSSTRESN",
    ]
    selected = [upper_by_original[item] for item in priority if item in upper_by_original]
    for column in columns:
        if column not in selected:
            selected.append(column)
        if len(selected) >= 8:
            break
    return selected


def _normal_pair_key(stem: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", stem.lower())


def _output_type_from_path(path: Path) -> str:
    stem = path.stem.lower()
    parts = {part.lower() for part in path.parts}
    if stem.startswith("t") or "tables" in parts:
        return "table"
    if stem.startswith("l") or "listings" in parts:
        return "listing"
    if stem.startswith("f") or "figures" in parts:
        return "figure"
    return "document"


def _display_id(stem: str, output_type: str) -> str:
    if re.match(r"^[tlf]-", stem.lower()):
        return stem
    prefix = {"table": "t", "listing": "l", "figure": "f"}.get(output_type, "")
    if prefix and stem.lower().startswith(prefix):
        return stem
    return stem


DOMAIN_HINTS = [
    "ae",
    "lb",
    "cm",
    "mh",
    "qs",
    "vs",
    "eg",
    "ex",
    "dv",
    "dm",
    "pe",
    "pr",
    "pc",
    "ec",
    "ce",
    "mo",
    "rp",
]


def _domain_hint(stem: str) -> str:
    compact = _normal_pair_key(stem)
    for token in DOMAIN_HINTS:
        if token in compact:
            return token.upper()
    return ""


def _title_hint(stem: str) -> str:
    tokens = [token for token in re.split(r"[^A-Za-z0-9]+", stem) if token]
    non_numeric = [token.upper() if len(token) <= 4 else token for token in tokens if not token.isdigit()]
    return " / ".join(non_numeric[:8])
