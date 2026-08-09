from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Protocol, Sequence

from packages.contracts.workbench_contracts import (
    CompetitiveProductSummary,
    EvidenceCandidateDetail,
    EvidenceCandidatePage,
    EvidenceCandidateSummary,
    EvidenceDesignPackageSummary,
    EvidencePackageCatalogSummary,
    EvidencePicosOptionTemplate,
    EvidencePicosQuestion,
    EvidenceQualityGate,
)


CRSWNP_ROOT = Path("/Users/smkzw/Documents/康哲项目资料/竞品调研/CRSwNP")
CRSWNP_MASTER_ROOT = CRSWNP_ROOT / "00_Master_Database"
PNH_ROOT = Path("/Users/smkzw/Documents/调研/PNH")
PNH_COMPETITOR_DB = PNH_ROOT / "03_extracted" / "pnh_competitor.sqlite"


class EvidencePackageAdapterError(RuntimeError):
    """Public, fail-closed source adapter diagnostic."""


@dataclass(frozen=True)
class EvidenceDesignPackageConfig:
    package_id: str
    package_label: str
    indication: str
    source_root: Path
    master_root: Path
    source_root_label: str
    package_role: str
    adapter_type: str = "crswnp_csv"
    sqlite_path: Optional[Path] = None


DEFAULT_EVIDENCE_PACKAGES = [
    EvidenceDesignPackageConfig(
        package_id="crswnp_competitive_evidence",
        package_label="CRSwNP竞品证据与方案设计资料包",
        indication="慢性鼻窦炎伴鼻息肉（CRSwNP）",
        source_root=CRSWNP_ROOT,
        master_root=CRSWNP_MASTER_ROOT,
        source_root_label="CRSwNP竞品调研原始资料与主数据库",
        package_role="方案设计证据底座与PICOS决策样本",
    ),
    EvidenceDesignPackageConfig(
        package_id="pnh_competitive_evidence",
        package_label="PNH竞品证据与方案设计资料包",
        indication="阵发性睡眠性血红蛋白尿（PNH）",
        source_root=PNH_ROOT,
        master_root=PNH_ROOT / "03_extracted",
        source_root_label="PNH竞品调研规范化数据库与原始来源索引",
        package_role="第二适应症证据适配、PICOS设计与跨项目验证资料包",
        adapter_type="pnh_sqlite",
        sqlite_path=PNH_COMPETITOR_DB,
    ),
]

EVIDENCE_PACKAGE_IDS_BY_PROJECT = {
    "proj_mgk10_crswnp": {"crswnp_competitive_evidence"},
    "proj_my008_pnh_3_01": {"pnh_competitive_evidence"},
}


class EvidencePackageAdapter(Protocol):
    config: EvidenceDesignPackageConfig

    def build_package(self) -> EvidenceDesignPackageSummary: ...

    def catalog_summary(self) -> EvidencePackageCatalogSummary: ...

    def candidate_page(
        self,
        *,
        candidate_type: str,
        page: int,
        page_size: int,
        search: str,
    ) -> EvidenceCandidatePage: ...

    def candidate_detail(self, evidence_id: str) -> EvidenceCandidateDetail: ...

    def source_hash(self) -> str: ...


class CrswnpCsvEvidenceAdapter:
    def __init__(
        self,
        config: EvidenceDesignPackageConfig,
        package_builder: Callable[[], EvidenceDesignPackageSummary],
    ):
        self.config = config
        self._package_builder = package_builder

    def build_package(self) -> EvidenceDesignPackageSummary:
        return self._package_builder()

    def catalog_summary(self) -> EvidencePackageCatalogSummary:
        package = self.build_package()
        return EvidencePackageCatalogSummary(
            package_id=package.package_id,
            package_label=package.package_label,
            indication=package.indication,
            source_root_label=package.source_root_label,
            package_role=package.package_role,
            product_count=len(package.products),
            candidate_count_by_type={
                "document": len(package.documents),
                "trial": len(package.trial_designs),
                "efficacy": len(package.efficacy_results),
                "safety": len(package.safety_results),
            },
            diagnostics=list(package.parser_warnings),
        )

    def candidate_page(
        self,
        *,
        candidate_type: str,
        page: int,
        page_size: int,
        search: str,
    ) -> EvidenceCandidatePage:
        candidates = self._candidates(candidate_type)
        filtered = _filter_candidates(candidates, search)
        start = (page - 1) * page_size
        items = [_summary(item) for item in filtered[start : start + page_size]]
        return EvidenceCandidatePage(
            project_id="",
            package_id=self.config.package_id,
            candidate_type=candidate_type,
            page=page,
            page_size=page_size,
            total=len(filtered),
            has_next=start + page_size < len(filtered),
            items=items,
        )

    def candidate_detail(self, evidence_id: str) -> EvidenceCandidateDetail:
        for item in self._candidates("all"):
            if item.evidence_id == evidence_id:
                return item
        raise KeyError(f"evidence candidate not found: {evidence_id}")

    def source_hash(self) -> str:
        paths = [
            self.config.master_root / name
            for name in ("Document_Index.csv", "Trial_Design.csv", "Efficacy_Result.csv", "Safety_Result.csv")
        ]
        return _files_hash(paths)

    def _candidates(self, candidate_type: str) -> List[EvidenceCandidateDetail]:
        allowed = {"all", "document", "trial", "efficacy", "safety"}
        if candidate_type not in allowed:
            raise ValueError(f"unsupported evidence candidate type: {candidate_type}")
        package = self.build_package()
        items: List[EvidenceCandidateDetail] = []
        if candidate_type in {"all", "document"}:
            for item in package.documents:
                source_refs = [ref for ref in [item.primary_source_id, item.relative_path] if ref]
                items.append(
                    _detail(
                        config=self.config,
                        evidence_type="document",
                        natural_key=item.document_id,
                        title=item.public_title,
                        drug_name=item.drug_name,
                        trial_identifier=item.trial_identifier,
                        source_status=item.verification_status or item.parser_status,
                        source_date=item.primary_source_date,
                        evidence_level=item.evidence_level,
                        source_refs=source_refs or [f"Document_Index:{item.document_id}"],
                        metadata={
                            "document_type": item.document_type,
                            "file_format": item.file_format,
                            "role_hint": item.role_hint,
                        },
                    )
                )
        if candidate_type in {"all", "trial"}:
            for item in package.trial_designs:
                items.append(
                    _detail(
                        config=self.config,
                        evidence_type="trial",
                        natural_key=item.trial_id,
                        title=item.trial_acronym or item.registry_id or item.primary_endpoint or item.trial_id,
                        drug_name=item.drug_name,
                        trial_identifier=item.registry_id or item.trial_id,
                        phase=item.phase,
                        source_status=item.verification_status or item.trial_status,
                        evidence_level=item.evidence_level,
                        source_refs=[f"Trial_Design:{item.trial_id}"],
                        metadata={
                            "sponsor": item.sponsor,
                            "design_type": item.design_type,
                            "primary_endpoint": item.primary_endpoint,
                            "primary_timepoint": item.primary_timepoint,
                        },
                    )
                )
        for result_type, rows in (("efficacy", package.efficacy_results), ("safety", package.safety_results)):
            if candidate_type not in {"all", result_type}:
                continue
            for item in rows:
                items.append(
                    _detail(
                        config=self.config,
                        evidence_type=result_type,
                        natural_key=item.result_id,
                        title=f"{item.endpoint_name} · {item.trial_identifier or item.trial_id}",
                        drug_name=item.drug_name,
                        trial_identifier=item.trial_identifier or item.trial_id,
                        source_status=item.verification_status,
                        evidence_level=item.evidence_level,
                        source_refs=[item.source_locator or f"{result_type}:{item.result_id}"],
                        metadata={
                            "endpoint_type": item.endpoint_type,
                            "timepoint": item.timepoint,
                            "effect_summary": item.effect_summary,
                            "source_type": item.source_type,
                        },
                    )
                )
        return sorted(items, key=lambda item: (item.evidence_type, item.primary_source_id))


class PnhSqliteEvidenceAdapter:
    REQUIRED_COLUMNS: Dict[str, set[str]] = {
        "trials": {
            "trial_uid",
            "official_title",
            "brief_title",
            "drug_name",
            "phase",
            "trial_status",
            "nct_id",
            "ctr_id",
            "source_refs",
        },
        "publications": {
            "publication_id",
            "trial_uid",
            "nct_id",
            "title",
            "year",
            "doi",
            "PMID",
            "PMCID",
            "url",
            "source_refs",
        },
        "regulatory_status": {
            "regulatory_id",
            "drug_id",
            "region",
            "product_name",
            "status",
            "application_number",
            "approval_or_submission_date",
            "source_refs",
        },
        "products": {"drug_id", "generic_name_en", "generic_name_cn", "target", "sponsor_current"},
    }

    def __init__(self, config: EvidenceDesignPackageConfig):
        self.config = config
        self.db_path = config.sqlite_path or config.master_root / "pnh_competitor.sqlite"

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise EvidencePackageAdapterError("PNH证据源不可用，请检查私有化部署的数据源配置。")
        try:
            connection = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            return connection
        except sqlite3.Error as exc:
            raise EvidencePackageAdapterError("PNH证据源无法以只读方式打开。") from exc

    def _validate(self, connection: sqlite3.Connection) -> None:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise EvidencePackageAdapterError("PNH证据源完整性检查未通过，已阻止生成部分结果。")
        missing: List[str] = []
        for table, required in self.REQUIRED_COLUMNS.items():
            rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
            columns = {str(row[1]) for row in rows}
            absent = sorted(required - columns)
            if absent:
                missing.append(f"{table}缺少字段:{','.join(absent)}")
        if missing:
            raise EvidencePackageAdapterError(f"PNH证据源结构不完整：{'；'.join(missing)}")
        self._validate_source_keys(connection)

    def _validate_source_keys(self, connection: sqlite3.Connection) -> None:
        key_specs = [
            ("trials", "trial", self._trial_key),
            ("publications", "publication", self._publication_key),
            ("regulatory_status", "regulatory", self._regulatory_key),
        ]
        for table, evidence_type, key_builder in key_specs:
            keys: List[str] = []
            for row in connection.execute(f"SELECT * FROM {table}"):
                try:
                    keys.append(key_builder(row))
                except ValueError as exc:
                    raise EvidencePackageAdapterError(
                        f"PNH证据源存在无法建立稳定标识的{evidence_type}记录。"
                    ) from exc
            if len(keys) != len(set(keys)):
                raise EvidencePackageAdapterError(
                    f"PNH证据源存在重复{evidence_type}自然键，已阻止覆盖既有审计记录。"
                )
            stable_ids = [_stable_evidence_id(self.config.package_id, evidence_type, key) for key in keys]
            if len(stable_ids) != len(set(stable_ids)):
                raise EvidencePackageAdapterError(
                    f"PNH证据源存在{evidence_type}稳定标识碰撞，已阻止生成候选池。"
                )

    def build_package(self) -> EvidenceDesignPackageSummary:
        with self._connect() as connection:
            self._validate(connection)
            products = [self._product(row) for row in connection.execute("SELECT * FROM products ORDER BY drug_id")]
            phase_counts = _counter_query(connection, "trials", "phase")
            status_counts = _counter_query(connection, "trials", "trial_status")
            trial_count = _count(connection, "trials")
            publication_count = _count(connection, "publications")
            regulatory_count = _count(connection, "regulatory_status")
            efficacy_count = _count(connection, "efficacy")
            safety_count = _count(connection, "safety")
            endpoint_count = _count(connection, "endpoints")
            registry_count = _count(connection, "evidence_registry")

        warnings = []
        if registry_count == 0:
            warnings.append("evidence_registry当前为空；候选证据从试验、发表和监管状态源表构建，并保留稳定来源标识。")
        return EvidenceDesignPackageSummary(
            package_id=self.config.package_id,
            package_label=self.config.package_label,
            indication=self.config.indication,
            source_root_label=self.config.source_root_label,
            package_role=self.config.package_role,
            total_product_count=len(products),
            total_trial_count=trial_count,
            total_document_count=publication_count + regulatory_count,
            total_result_count=efficacy_count + safety_count,
            candidate_count_by_type={
                "trial": trial_count,
                "publication": publication_count,
                "regulatory": regulatory_count,
            },
            products=products,
            trial_count_by_phase=phase_counts,
            trial_count_by_status=status_counts,
            document_count_by_type={"Publication": publication_count, "Regulatory": regulatory_count},
            endpoint_count_by_name={"结构化终点": endpoint_count},
            safety_row_count=safety_count,
            picos_questions=_pnh_picos_questions(trial_count, endpoint_count),
            quality_gates=_pnh_quality_gates(registry_count),
            parser_warnings=warnings,
        )

    def catalog_summary(self) -> EvidencePackageCatalogSummary:
        package = self.build_package()
        return EvidencePackageCatalogSummary(
            package_id=package.package_id,
            package_label=package.package_label,
            indication=package.indication,
            source_root_label=package.source_root_label,
            package_role=package.package_role,
            product_count=package.total_product_count,
            candidate_count_by_type=package.candidate_count_by_type,
            diagnostics=list(package.parser_warnings),
        )

    def candidate_page(
        self,
        *,
        candidate_type: str,
        page: int,
        page_size: int,
        search: str,
    ) -> EvidenceCandidatePage:
        candidates = self._candidates(candidate_type)
        filtered = _filter_candidates(candidates, search)
        start = (page - 1) * page_size
        return EvidenceCandidatePage(
            project_id="",
            package_id=self.config.package_id,
            candidate_type=candidate_type,
            page=page,
            page_size=page_size,
            total=len(filtered),
            has_next=start + page_size < len(filtered),
            items=[_summary(item) for item in filtered[start : start + page_size]],
        )

    def candidate_detail(self, evidence_id: str) -> EvidenceCandidateDetail:
        for item in self._candidates("all"):
            if item.evidence_id == evidence_id:
                return item
        raise KeyError(f"evidence candidate not found: {evidence_id}")

    def source_hash(self) -> str:
        if not self.db_path.exists():
            raise EvidencePackageAdapterError("PNH证据源不可用，请检查私有化部署的数据源配置。")
        return _files_hash([self.db_path])

    def _candidates(self, candidate_type: str) -> List[EvidenceCandidateDetail]:
        allowed = {"all", "trial", "publication", "regulatory"}
        if candidate_type not in allowed:
            raise ValueError(f"unsupported evidence candidate type: {candidate_type}")
        with self._connect() as connection:
            self._validate(connection)
            items: List[EvidenceCandidateDetail] = []
            if candidate_type in {"all", "trial"}:
                items.extend(self._trial(row) for row in connection.execute("SELECT * FROM trials ORDER BY trial_uid"))
            if candidate_type in {"all", "publication"}:
                items.extend(
                    self._publication(row)
                    for row in connection.execute("SELECT * FROM publications ORDER BY publication_id")
                )
            if candidate_type in {"all", "regulatory"}:
                items.extend(
                    self._regulatory(row)
                    for row in connection.execute("SELECT * FROM regulatory_status ORDER BY regulatory_id")
                )
        return items

    def _product(self, row: sqlite3.Row) -> CompetitiveProductSummary:
        name = _first(row["generic_name_cn"], row["generic_name_en"], row["drug_id"])
        return CompetitiveProductSummary(
            product_id=f"product:{_stable_token(str(row['drug_id']))}",
            drug_name=name,
            target=_text(row["target"]),
            sponsor=_text(row["sponsor_current"]),
        )

    def _trial(self, row: sqlite3.Row) -> EvidenceCandidateDetail:
        natural_key = self._trial_key(row)
        refs = _source_refs(row["source_refs"], fallback=f"trials:{natural_key}")
        title = _first(row["brief_title"], row["official_title"], row["study_acronym"], natural_key)
        return _detail(
            config=self.config,
            evidence_type="trial",
            natural_key=natural_key,
            title=title,
            drug_name=_text(row["drug_name"]),
            trial_identifier=_first(row["nct_id"], row["ctr_id"], natural_key),
            phase=_text(row["phase"]),
            source_status=_text(row["trial_status"]),
            source_date=_first(row["primary_completion_date"], row["completion_date"], row["start_date"]),
            source_refs=refs,
            metadata={
                "source_alias": _text(row["trial_uid"]),
                "sponsor": _text(row["sponsor"]),
                "condition": _text(row["condition"]),
                "study_type": _text(row["study_type"]),
                "design": _first(row["trial_design_summary_cn"], row["allocation"]),
                "population": _text(row["population_position_cn"]),
                "primary_endpoints": _text(row["primary_endpoints_summary_cn"]),
            },
        )

    def _publication(self, row: sqlite3.Row) -> EvidenceCandidateDetail:
        natural_key = self._publication_key(row)
        refs = _source_refs(row["source_refs"], fallback=f"publications:{natural_key}")
        return _detail(
            config=self.config,
            evidence_type="publication",
            natural_key=natural_key,
            title=_first(row["title"], natural_key),
            trial_identifier=_first(row["nct_id"], row["trial_uid"]),
            source_status=_text(row["inclusion_in_core_analysis"]),
            source_date=_text(row["year"]),
            source_refs=refs,
            metadata={
                "source_alias": _text(row["publication_id"]),
                "journal_or_conference": _text(row["journal_or_conference"]),
                "publication_type": _text(row["publication_type"]),
                "doi": _text(row["doi"]),
                "pmid": _text(row["PMID"]),
            },
        )

    def _regulatory(self, row: sqlite3.Row) -> EvidenceCandidateDetail:
        natural_key = self._regulatory_key(row)
        refs = _source_refs(row["source_refs"], fallback=f"regulatory_status:{natural_key}")
        title = " · ".join(
            item
            for item in [_text(row["product_name"]), _text(row["region"]), _text(row["status"])]
            if item
        ) or natural_key
        return _detail(
            config=self.config,
            evidence_type="regulatory",
            natural_key=natural_key,
            title=title,
            drug_name=_text(row["drug_id"]),
            source_status=_text(row["status"]),
            source_date=_text(row["approval_or_submission_date"]),
            source_refs=refs,
            metadata={
                "source_alias": _text(row["regulatory_id"]),
                "region": _text(row["region"]),
                "application_number": _text(row["application_number"]),
                "indication": _text(row["indication"]),
                "key_label_claims": _text(row["key_label_claims"]),
            },
        )

    @staticmethod
    def _trial_key(row: sqlite3.Row) -> str:
        nct_id = _canonical_identifier("ctgov", row["nct_id"])
        if not nct_id or not re.fullmatch(r"ctgov:nct\d{8}", nct_id):
            raise ValueError("trial nct_id is missing or invalid")
        return nct_id

    @staticmethod
    def _publication_key(row: sqlite3.Row) -> str:
        for namespace, column in (("doi", "doi"), ("pmid", "PMID"), ("pmcid", "PMCID"), ("url", "url")):
            value = _canonical_identifier(namespace, row[column])
            if value:
                return value
        raise ValueError("publication has no durable identifier")

    @staticmethod
    def _regulatory_key(row: sqlite3.Row) -> str:
        region = _normalized_text(row["region"])
        application_number = _normalized_text(row["application_number"])
        if region and _is_authoritative_application_number(region, application_number):
            return f"{region}:application:{application_number}"
        drug_id = _normalized_text(row["drug_id"])
        product_name = _normalized_text(row["product_name"])
        if region and drug_id and product_name:
            return f"{region}:product:{drug_id}:{product_name}"
        raise ValueError("regulatory record has no durable identifier")


def _detail(
    *,
    config: EvidenceDesignPackageConfig,
    evidence_type: str,
    natural_key: str,
    title: str,
    source_refs: Sequence[str],
    drug_name: str = "",
    trial_identifier: str = "",
    phase: str = "",
    source_status: str = "",
    source_date: str = "",
    evidence_level: str = "",
    metadata: Optional[Dict[str, str]] = None,
) -> EvidenceCandidateDetail:
    public_refs = [_public_ref(ref) for ref in source_refs if _public_ref(ref)]
    safe_metadata = {key: _public_ref(value) for key, value in (metadata or {}).items() if _public_ref(value)}
    search_text = " ".join(
        [title, natural_key, drug_name, trial_identifier, phase, source_status, source_date, *safe_metadata.values()]
    )
    return EvidenceCandidateDetail(
        evidence_id=_stable_evidence_id(config.package_id, evidence_type, natural_key),
        package_id=config.package_id,
        evidence_type=evidence_type,
        title=_public_ref(title) or "未命名证据",
        primary_source_id=natural_key,
        drug_name=drug_name,
        trial_identifier=trial_identifier,
        phase=phase,
        source_status=source_status,
        source_date=source_date,
        evidence_level=evidence_level,
        source_ref_count=len(public_refs),
        search_text=search_text,
        source_refs=public_refs,
        provenance={"source_table": evidence_type, "natural_key": natural_key},
        metadata=safe_metadata,
    )


def _summary(detail: EvidenceCandidateDetail) -> EvidenceCandidateSummary:
    return EvidenceCandidateSummary(
        **{field: getattr(detail, field) for field in EvidenceCandidateSummary.model_fields}
    )


def _filter_candidates(
    candidates: Sequence[EvidenceCandidateDetail], search: str
) -> List[EvidenceCandidateDetail]:
    query = search.strip().lower()
    if not query:
        return list(candidates)
    return [item for item in candidates if query in item.search_text.lower()]


def _stable_evidence_id(package_id: str, evidence_type: str, natural_key: str) -> str:
    digest = sha256(f"v1|{evidence_type}|{natural_key.strip()}".encode("utf-8")).hexdigest()[:20]
    return f"{package_id}:{evidence_type}:v1:{digest}"


def _files_hash(paths: Iterable[Path]) -> str:
    digest = sha256()
    for path in sorted(paths, key=lambda item: item.name):
        if not path.exists():
            raise EvidencePackageAdapterError(f"证据源文件缺失：{path.name}")
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _normalized_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", _text(value))
    text = " ".join(text.split()).strip().lower()
    return "" if text in {"", "na", "n/a", "none", "null", "unknown", "未检索", "未查询"} else text


def _canonical_identifier(namespace: str, value: object) -> str:
    text = _normalized_text(value)
    if not text:
        return ""
    if namespace == "doi":
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if text.startswith(prefix):
                text = text[len(prefix) :]
                break
    return f"{namespace}:{text}"


def _is_authoritative_application_number(region: str, value: str) -> bool:
    if not value:
        return False
    if region == "fda":
        return bool(re.fullmatch(r"(?:bla|nda)\d+", value))
    if region == "ema":
        return bool(re.fullmatch(r"emea/h/c/\d+", value))
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9./-]{3,39}", value))


def _stable_token(text: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in text).strip("_")[:48] or "unknown"


def _text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat", "未检索"} else text


def _first(*values: object) -> str:
    return next((_text(value) for value in values if _text(value)), "")


def _public_ref(value: object) -> str:
    text = _text(value)
    if not text:
        return ""
    if "/Users/" in text:
        return Path(text).name
    return text


def _source_refs(value: object, *, fallback: str) -> List[str]:
    text = _text(value)
    if not text:
        return [fallback]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        refs = [_public_ref(item) for item in parsed if _public_ref(item)]
        return refs or [fallback]
    if isinstance(parsed, dict):
        refs = [_public_ref(item) for item in parsed.values() if _public_ref(item)]
        return refs or [fallback]
    refs = [_public_ref(item) for item in text.replace("|", ";").split(";") if _public_ref(item)]
    return refs or [fallback]


def _count(connection: sqlite3.Connection, table: str) -> int:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return 0
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _counter_query(connection: sqlite3.Connection, table: str, column: str) -> Dict[str, int]:
    return {
        _text(row[0]): int(row[1])
        for row in connection.execute(
            f"SELECT {column}, COUNT(*) FROM {table} WHERE TRIM(COALESCE({column}, '')) <> '' GROUP BY {column}"
        )
    }


def _pnh_quality_gates(registry_count: int) -> List[EvidenceQualityGate]:
    return [
        EvidenceQualityGate(
            gate_id="pnh_competitive_evidence:gate:source_boundary",
            gate_label="来源边界已锁定",
            status="ok",
            owner="医学经理",
            detail="候选池从PNH规范化试验、发表和监管状态源表重建；既有报告仅作为QA参考。",
            source_refs=["trials", "publications", "regulatory_status"],
        ),
        EvidenceQualityGate(
            gate_id="pnh_competitive_evidence:gate:registry",
            gate_label="证据登记表覆盖检查",
            status="warning" if registry_count == 0 else "ok",
            owner="数据管理员",
            detail="evidence_registry为空时，系统使用源表自然键构建稳定候选标识，不将空登记表误判为无证据。",
            source_refs=["evidence_registry", "trials", "publications", "regulatory_status"],
        ),
        EvidenceQualityGate(
            gate_id="pnh_competitive_evidence:gate:picos_handoff",
            gate_label="PICOS输出需医学批准",
            status="blocked",
            owner="医学经理/医学总监",
            detail="PNH PICOS候选需完成来源核对、医学确认和医学批准后方可进入撰写交接。",
            source_refs=["PICOS decision queue"],
        ),
    ]


def _pnh_picos_questions(trial_count: int, endpoint_count: int) -> List[EvidencePicosQuestion]:
    common = {
        "evidence_status": "evidence_available_needs_medical_decision",
        "handoff_to_writing": True,
    }
    return [
        EvidencePicosQuestion(
            question_id="picos:population",
            picos_domain="P - 研究人群",
            question="目标PNH研究人群应如何界定既往补体抑制剂使用、贫血/溶血负担、输血需求及血栓风险？",
            current_evidence_summary=f"PNH试验源表覆盖{trial_count}项研究，并保留既往补体抑制剂、Hb/LDH、输血、疫苗和合并治疗字段。",
            required_user_decision="由医学确认目标治疗线、既往治疗状态、疾病活动度阈值和风险分层。",
            source_refs=["trials:key_inclusion_cn", "trials:prior_complement_inhibitor_requirement"],
            option_templates=[
                EvidencePicosOptionTemplate(label="补体抑制剂初治高疾病负担人群", design_summary="聚焦存在活动性溶血、贫血或输血需求且未接受补体抑制剂的人群。", medical_rationale_prompt="请说明Hb、LDH、输血史和血栓风险阈值。", risk_notes=["需核对地区标准治疗和疫苗/抗菌预防要求。"]),
                EvidencePicosOptionTemplate(label="既往C5抑制剂治疗后残余贫血人群", design_summary="聚焦既往C5抑制剂治疗后仍存在残余贫血、输血或血管外溶血负担的人群。", medical_rationale_prompt="请说明既往治疗稳定期、残余疾病负担和切换标准。", risk_notes=["需避免把不同机制产品的既往治疗要求直接等同。"]),
                EvidencePicosOptionTemplate(label="混合人群并按既往治疗分层", design_summary="纳入初治和经治人群，并预设分层与交互作用解释。", medical_rationale_prompt="请说明混合人群的注册定位、分层因素和样本量影响。", risk_notes=["异质性可能稀释总体效应。"]),
            ],
            **common,
        ),
        EvidencePicosQuestion(
            question_id="picos:intervention",
            picos_domain="I - 干预措施",
            question="干预方案应采用单药、切换或联合策略，剂量、途径、频率和预防性治疗如何设置？",
            current_evidence_summary="试验源表保留治疗臂、给药、背景治疗、疫苗/抗菌预防、救援治疗和停药规则。",
            required_user_decision="由医学确认目标机制下的给药方案、切换/联合窗口及安全管理要求。",
            source_refs=["trials:arms_summary_cn", "trials:vaccination_or_antibiotic_requirement"],
            option_templates=[
                EvidencePicosOptionTemplate(label="目标机制单药方案", design_summary="采用机制匹配的固定单药方案，并统一疫苗、抗菌预防和救援治疗。", medical_rationale_prompt="请说明剂量和给药频率的PK/PD及既往研究依据。", risk_notes=["需补产品自身剂量探索证据。"]),
                EvidencePicosOptionTemplate(label="既往治疗切换方案", design_summary="设置从既往补体抑制剂切换至研究药物的明确窗口和重叠规则。", medical_rationale_prompt="请说明洗脱、重叠、突破性溶血监测和失败处理。", risk_notes=["切换窗口可能带来疾病反跳风险。"]),
                EvidencePicosOptionTemplate(label="联合或序贯探索方案", design_summary="在残余疾病负担人群中探索联合或序贯治疗。", medical_rationale_prompt="请说明联合依据、停药规则和归因边界。", risk_notes=["安全性归因和监管解释更复杂。"]),
            ],
            **common,
        ),
        EvidencePicosQuestion(
            question_id="picos:comparator",
            picos_domain="C - 对照",
            question="对照应采用标准补体抑制剂、标准治疗背景下安慰剂，还是基线内对照/切换设计？",
            current_evidence_summary="PNH试验源表保留随机、盲法、对照类型、比较药、切换和交叉字段。",
            required_user_decision="由医学确认伦理可接受、临床相关且支持目标标签的对照策略。",
            source_refs=["trials:control_type", "trials:comparator", "trials:crossover_or_switch"],
            option_templates=[
                EvidencePicosOptionTemplate(label="标准补体抑制剂活性对照", design_summary="以当前标准补体抑制剂作为活性对照并预设非劣/优效目标。", medical_rationale_prompt="请说明比较药选择、效应界值和背景治疗一致性。", risk_notes=["需要统计和监管共同确认界值。"]),
                EvidencePicosOptionTemplate(label="标准治疗背景下安慰剂对照", design_summary="仅在伦理与救援治疗充分保障的场景考虑安慰剂。", medical_rationale_prompt="请说明伦理依据、救援阈值和暴露窗口。", risk_notes=["高疾病负担PNH人群可能不适合长期安慰剂。"]),
                EvidencePicosOptionTemplate(label="切换或基线内对照", design_summary="对稳定经治人群采用切换或基线内变化设计。", medical_rationale_prompt="请说明基线稳定期、周期效应和回归均值控制。", risk_notes=["解释性和监管接受度需单独确认。"]),
            ],
            **common,
        ),
        EvidencePicosQuestion(
            question_id="picos:outcomes",
            picos_domain="O - 终点",
            question="主要和关键次要终点应如何组合Hb稳定、输血避免、LDH/溶血、疲劳/生活质量及突破性溶血？",
            current_evidence_summary=f"PNH数据库已结构化登记{endpoint_count}条终点记录，并关联疗效、安全性和来源定位。",
            required_user_decision="由医学确认终点层级、评价窗口、临床意义阈值、多重性和安全性关注项。",
            source_refs=["endpoints", "efficacy", "safety"],
            option_templates=[
                EvidencePicosOptionTemplate(label="Hb稳定与输血避免双核心终点", design_summary="围绕Hb稳定/改善和输血避免构建主要或关键终点体系。", medical_rationale_prompt="请说明阈值、评价窗口和输血规则。", risk_notes=["需处理输血作为干预事件对Hb评价的影响。"]),
                EvidencePicosOptionTemplate(label="溶血控制与患者获益组合", design_summary="组合LDH、突破性溶血、FACIT-Fatigue和生活质量评价。", medical_rationale_prompt="请说明客观指标与患者报告结局的层级和临床意义。", risk_notes=["工具版本与多重性需预先确认。"]),
                EvidencePicosOptionTemplate(label="残余贫血与血管外溶血聚焦", design_summary="对既往C5治疗人群强化Hb、网织红细胞、胆红素、输血和症状评价。", medical_rationale_prompt="请说明残余贫血机制和终点选择的对应关系。", risk_notes=["需避免仅凭跨试验差异推断机制优劣。"]),
            ],
            **common,
        ),
        EvidencePicosQuestion(
            question_id="picos:study_design",
            picos_domain="S - 研究设计",
            question="研究应采用随机活性对照、经治人群切换设计或单臂难治队列，并如何设置延长期？",
            current_evidence_summary="PNH试验源表保留研究阶段、随机、盲法、治疗期、随访、extension/rollover及停药规则。",
            required_user_decision="由医学确认开发阶段、主要研究目的、对照框架、治疗期和长期安全性策略。",
            source_refs=["trials:trial_design_summary_cn", "trials:extension_or_rollover"],
            option_templates=[
                EvidencePicosOptionTemplate(label="随机活性对照确证性设计", design_summary="采用随机、平行、活性对照并设置长期延长期。", medical_rationale_prompt="请说明优效/非劣目标、分层和延长期转换规则。", risk_notes=["样本量和界值依赖可靠历史证据。"]),
                EvidencePicosOptionTemplate(label="稳定经治人群随机切换设计", design_summary="在稳定标准治疗人群中随机继续原治疗或切换研究药物。", medical_rationale_prompt="请说明稳定期、切换期和突破性溶血管理。", risk_notes=["切换风险和开放标签影响需控制。"]),
                EvidencePicosOptionTemplate(label="难治/残余疾病单臂队列", design_summary="对高度选择的难治或残余疾病人群采用单臂前后对照并强化外部证据。", medical_rationale_prompt="请说明未满足需求、外部对照和偏倚控制。", risk_notes=["证据等级和监管解释受限。"]),
            ],
            **common,
        ),
    ]
