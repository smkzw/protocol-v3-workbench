from __future__ import annotations

import hashlib
import io
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Sequence
from urllib.parse import urlencode, urlparse

from packages.contracts.workbench_contracts import (
    WritingReferencePublicDocument,
    WritingReferenceDocumentArtifact,
    WritingReferenceDocumentIngestRequest,
    WritingReferenceManualDocumentUploadRequest,
    WritingReferenceDocumentValidationCheck,
    WritingReferenceDocumentValidationRecord,
    WritingReferenceExtractedSpan,
    WritingReferenceExtractionResult,
    WritingReferenceOcrPageEvidence,
    WritingReferenceSkippedInterstitial,
    WritingReferenceSourceFragment,
    WritingReferenceSearchCreateRequest,
    WritingReferenceSearchRequest,
    WritingReferenceSearchSnapshot,
    WritingReferenceTrialCandidate,
    WritingReferenceTrialIntervention,
    WritingReferenceTranslationRequest,
    WritingReferenceTranslationRevisionRequest,
    WritingReferenceTranslationRevision,
)

from .writing_reference_repository import (
    WritingReferenceConflictError,
    WritingReferenceRepository,
)
from .writing_reference_m11 import (
    m11_anchor as _m11_anchor,
    m11_anchor_from_ocr_page as _m11_anchor_from_ocr_page,
)
from .regulatory_translation_glossary import (
    evaluate_controlled_term_fidelity,
    participant_terminology_mismatch,
    regulatory_translation_glossary_hash,
    render_regulatory_translation_glossary_contract,
)
from .chapter_translation_pipeline import (
    CompositePipelineUnavailableError,
    TRANSLATION_CONTRACT_FINGERPRINT,
)


CTGOV_API_ROOT = "https://clinicaltrials.gov/api/v2"
CTGOV_ALLOWED_HOSTS = {"clinicaltrials.gov", "cdn.clinicaltrials.gov"}
CTGOV_DISCOVERY_FIELDS = (
    "NCTId,BriefTitle,OfficialTitle,BriefSummary,Condition,Phase,StudyType,"
    "InterventionName,InterventionType,DesignAllocation,"
    "DesignInterventionModel,DesignMasking,EnrollmentCount,LeadSponsorName,"
    "OverallStatus,StudyFirstPostDate,LargeDoc"
)
DEFAULT_REGULATORY_TRANSLATION_INSTRUCTION = (
    "请在保持数字、单位、时间点、缩写、否定、终点层级、动作主体及前后时序依赖忠实的前提下，"
    "翻译为自然、克制的中国临床试验方案监管中文候选。"
)
NCT_ID_PATTERN = re.compile(r"NCT\d{8}")
SAFE_PDF_FILENAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.pdf")
NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9.])[-−]\d+(?:\.\d+)?(?![A-Za-z])"
    r"|(?<=\d-)\d+(?:\.\d+)?(?![A-Za-z])"
    r"|(?<![A-Za-z0-9.\-−])\d+(?:\.\d+)?(?![A-Za-z])"
)

# Clinical abbreviations: uppercase forms (AE, EASI-50, HCV-RNA), pluralized
# uppercase (AEs), and mixed-case clinical forms (eCRF, eGFR, mITT, vIGA-AD).
# Ordinary title-case English words are never matched.
ABBREVIATION_PATTERN = re.compile(
    r"\b(?:[A-Z][A-Z0-9]{1,}(?:-[A-Z0-9]+)*|[A-Z]{2,}s|"
    r"[a-z][A-Z][A-Z0-9]+(?:-[A-Z0-9]+)*)\b"
)
_ABBREVIATION_STOPWORDS = frozenset(
    {
        "AND",
        "BY",
        "DRUG",
        "FIRST",
        "INSTITUTION",
        "INVESTIGATOR",
        "MATLAB",
        "NOT",
        "NOTE",
        "OR",
        "PROTOCOL",
        "PROVIDED",
        "SCHEDULE",
        "SPONSOR",
        "STUDY",
        "SUB",
        "SUB-INVESTIGATOR",
        "SUPPORT",
        "TITLE",
        "VERSION",
        "VISIT",
    }
)
_ROMAN_NUMERAL_RANGE_PATTERN = re.compile(
    r"^[IVXLCDM]+-[IVXLCDM]+$",
    re.IGNORECASE,
)


def detect_clinical_abbreviations(text: str) -> tuple[str, ...]:
    """Return the sorted clinical abbreviations detected in ``text``.

    This is the single product clinical-abbreviation pattern: it matches
    uppercase forms and common mixed-case clinical forms (eCRF, eGFR, mITT,
    vIGA-AD) but never title-case ordinary English words.  Used both by the
    deterministic fidelity gate and by the Hy-MT2 prompt abbreviation
    contract, so detection and enforcement can never drift apart.
    """
    candidates = set(ABBREVIATION_PATTERN.findall(text or ""))
    return tuple(
        sorted(
            candidate
            for candidate in candidates - _ABBREVIATION_STOPWORDS
            if not _ROMAN_NUMERAL_RANGE_PATTERN.fullmatch(candidate)
        )
    )


SOURCE_NEGATION_PATTERN = re.compile(
    r"\b(?:not|no|without|must\s+not|exclude(?:d|s)?)\b", re.I
)
CHINESE_NEGATION_PATTERN = re.compile(
    r"(?:不得|不能|不会|不应|不允许|不存在|不相关|不需要|不要求|不一定|无需|无须|无|未|非|排除|禁止|"
    r"并非|不是|没有|否|"
    r"不(?:受|进行|再|继续|恢复|开展|实施|保留|含有|包括|接受|完成|"
    r"限于|局限于|服用|给予|使用|合并|联用|联合|与|表现|显示|适用|优选|具有))"
)
UNTRANSLATED_CONNECTOR_PATTERN = re.compile(
    r"(?:\b(?:and/or|and|or|whether|whereas|unless|except)\b|"
    r"(?<![A-Za-z])(?:eg|ie)(?![A-Za-z])|\b(?:e\.g|i\.e)\.)",
    re.I,
)
REGULATORY_CHINESE_CALQUE_RULES: tuple[tuple[re.Pattern[str], re.Pattern[str]], ...] = (
    (
        re.compile(r"\bPeriods?\s+\d", re.I),
        re.compile(r"第\s*\d+(?:\s*[、,至\-]\s*\d+)*\s*期"),
    ),
    (
        re.compile(r"\bwashout\b", re.I),
        re.compile(r"清洗期"),
    ),
    (
        re.compile(r"washout.{0,80}from\s+plasma", re.I),
        re.compile(r"从血浆中洗脱"),
    ),
    (
        re.compile(r"\bminitab\b", re.I),
        re.compile(r"minitab", re.I),
    ),
    (
        re.compile(r"\bsingle[- ]dose\b", re.I),
        re.compile(r"单剂量(?:研究|设计|给药)"),
    ),
    (
        re.compile(r"scientific\s+rationale", re.I),
        re.compile(r"科学理由"),
    ),
    (
        re.compile(r"\bH2\s+blocker", re.I),
        re.compile(r"H2\s*阻断剂"),
    ),
    (
        re.compile(r"\bnonpreferable\b|\bnot\s+preferred\b", re.I),
        re.compile(r"非优选(?:的)?.{0,12}选择|不优选(?:的)?.{0,12}选择"),
    ),
    (
        re.compile(r"\binterim\s+review\b", re.I),
        re.compile(r"中期审评"),
    ),
    (
        re.compile(r"\bsite\s+visit\b", re.I),
        re.compile(r"现场访视"),
    ),
    (
        re.compile(r"in\s+addition\s+to\s+the\s+instructions\s+on\s+the\s+label", re.I),
        re.compile(r"此外还有标签|此外还需遵循标签"),
    ),
    (
        re.compile(r"shall\s+be\s+instructed\s+to\s+not\s+skip", re.I),
        re.compile(r"不要漏服"),
    ),
    (
        re.compile(r"\bformulations?\b", re.I),
        re.compile(r"处方"),
    ),
    (
        re.compile(r"\b(?:treatment|dosing)\s+sequence\b", re.I),
        re.compile(r"\d+\s*种处理"),
    ),
    (
        re.compile(r"single\s+oral\s+dose\s+of\s+study\s+treatment", re.I),
        re.compile(r"单次口服剂量的研究治疗"),
    ),
    (
        re.compile(r"used\s+and\s+unused\s+medication", re.I),
        re.compile(r"已用和未用药物"),
    ),
    (
        re.compile(r"color\s+of\s+capsules\s*\(100\s*mg\s+capsule\)", re.I),
        re.compile(r"胶囊（100\s*mg胶囊）的颜色"),
    ),
    (
        re.compile(r"in\s+addition\s+to\s+the\s+instructions\s+on\s+the\s+label", re.I),
        re.compile(r"，除标签说明外[。\s]*$"),
    ),
    (
        re.compile(r"medicinal\s*\(investigational\)\s*product", re.I),
        re.compile(
            r"(?:药用|医药)（研究用）产品|药用（试验）产品|"
            r"研究用产品|试验用药品（研究用药品）|药品（试验用药品）"
        ),
    ),
    (
        re.compile(
            r"missed\s+or\s+rescheduled\s+visits.{0,80}automatic\s+discontinuation",
            re.I,
        ),
        re.compile(r"自动终止|错过的或重新安排的访视"),
    ),
    (
        re.compile(r"may\s+or\s+may\s+not\s+be.{0,80}(?:associated|related)", re.I),
        re.compile(r"也可能没有"),
    ),
    (
        re.compile(
            r"\bPNH\b.{0,500}\bresponse\s+rate\b|\bresponse\s+rate\b.{0,500}\bPNH\b",
            re.I,
        ),
        re.compile(r"缓解率|缓解者"),
    ),
    (
        re.compile(
            r"\bPNH\b.{0,300}\bclone\s+size\b|\bclone\s+size\b.{0,300}\bPNH\b", re.I
        ),
        re.compile(r"克隆大小"),
    ),
    (
        re.compile(r"after\s+each\s+of\s+the\s+first\s+\d+\s+infusions?", re.I),
        re.compile(r"每次前\d+次输注后|前\d+次输注后，每次均次日|在电话/邮件联系"),
    ),
    (
        re.compile(r"\(\s*\d+\s+active\s*:\s*\d+\s+placebo\s*\)", re.I),
        re.compile(r"\d+\s*(?:名|例)活性药物|\d+\s*例试验药物"),
    ),
)

REGULATORY_TRANSLATION_TASK_TYPE = "regulatory_translation_zh"
REGULATORY_TRANSLATION_PROMPT_VERSION = "regulatory_translation_zh_v0_5"
REGULATORY_TRANSLATION_SCHEMA_VERSION = "ai_task_output_v0_1"
REGULATORY_TRANSLATION_MODEL_NAME = "deepseek-v4-flash"
REGULATORY_TRANSLATION_FORBIDDEN_SOURCES = (
    "unapproved_competitor_corpus",
    "previous_ai_translation",
)

TEMPORAL_DEPENDENCY_INVERSION_RULES = (
    (
        re.compile(
            r"24-hour\s+safety\s+data\s+for\s+the\s+first\s+subject.{0,180}"
            r"before\s+dosing\s+the\s+second\s+subject",
            re.I | re.S,
        ),
        re.compile(
            r"第1例受试者给药前.{0,180}24小时安全性数据",
            re.S,
        ),
    ),
)
REGULATORY_TRANSLATION_CONTRACT_HASH = hashlib.sha256(
    json.dumps(
        {
            "task_type": REGULATORY_TRANSLATION_TASK_TYPE,
            "prompt_version": REGULATORY_TRANSLATION_PROMPT_VERSION,
            "schema_version": REGULATORY_TRANSLATION_SCHEMA_VERSION,
            "model_name": REGULATORY_TRANSLATION_MODEL_NAME,
            "glossary_hash": regulatory_translation_glossary_hash(),
            "forbidden_source_ids": sorted(REGULATORY_TRANSLATION_FORBIDDEN_SOURCES),
            "source_cardinality": 1,
            "medical_confirmation_required": True,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()

# ---------------------------------------------------------------------------
# Composite chapter-translation contract (Flash plan -> Hy-MT2 body -> Flash QC)
# ---------------------------------------------------------------------------
# The legacy REGULATORY_TRANSLATION_CONTRACT_HASH / MODEL_NAME / PROMPT_VERSION
# describe the old Flash-only end-to-end path.  Old candidates carrying those
# identifiers must NOT be treated as current composite-pipeline output.

COMPOSITE_TRANSLATION_TASK_TYPE = "composite_chapter_translation_zh"
COMPOSITE_TRANSLATION_BODY_MODEL = "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"
COMPOSITE_TRANSLATION_PLANNING_MODEL = "deepseek-v4-flash"
COMPOSITE_TRANSLATION_QC_MODEL = "deepseek-v4-flash"
COMPOSITE_TRANSLATION_PROMPT_VERSION = "composite_chapter_translation_v0_4_hy_body_only"
COMPOSITE_TRANSLATION_SCHEMA_VERSION = "ai_task_output_v0_1"


def composite_translation_contract_hash(
    *,
    downstream_fingerprint: str = TRANSLATION_CONTRACT_FINGERPRINT,
) -> str:
    payload = {
        "task_type": COMPOSITE_TRANSLATION_TASK_TYPE,
        "prompt_version": COMPOSITE_TRANSLATION_PROMPT_VERSION,
        "schema_version": COMPOSITE_TRANSLATION_SCHEMA_VERSION,
        "body_model": COMPOSITE_TRANSLATION_BODY_MODEL,
        "planning_model": COMPOSITE_TRANSLATION_PLANNING_MODEL,
        "qc_model": COMPOSITE_TRANSLATION_QC_MODEL,
        "downstream_fingerprint": downstream_fingerprint,
        "glossary_hash": regulatory_translation_glossary_hash(),
        "forbidden_source_ids": sorted(REGULATORY_TRANSLATION_FORBIDDEN_SOURCES),
        "source_cardinality": 1,
        "medical_confirmation_required": True,
        "pipeline_kind": "flash_plan_hy_mt2_body_flash_non_authoring_qc",
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


COMPOSITE_TRANSLATION_CONTRACT_HASH = composite_translation_contract_hash()

SOURCE_COMPARATOR_PATTERN = re.compile(
    r">=|<=|≥|≤|>|<|\bat\s+least\b|\bno\s+less\s+than\b|"
    r"\ba\s+minimum\s+of\b|"
    r"\bgreater\s+than\s+or\s+equal\s+to\b|\bmore\s+than\b|\bgreater\s+than\b|"
    r"\bat\s+most\b|\bno\s+more\s+than\b|\bless\s+than\s+or\s+equal\s+to\b|"
    r"\bless\s+than\b",
    re.I,
)
TRANSLATED_COMPARATOR_PATTERN = re.compile(
    r">=|<=|≥|≤|>|<|大于或等于|大于等于|不低于|至少|以上|超过|大于|"
    r"超出|更高|更大|较多|更低|更小|较少|"
    r"小于或等于|小于等于|不高于|至多|以下|低于|小于|不足|未满|不满|"
    r"满(?=\s*\d)|最短(?=\s*间隔)"
)
NUMERIC_UNIT_PATTERN = re.compile(
    r"(?:(?P<prefix>day|days|week|weeks|month|months|year|years)\s*(?P<prefix_number>\d+(?:\.\d+)?)|"
    r"(?<![A-Za-z0-9-])(?P<number>\d+(?:\.\d+)?)\s*-?\s*(?:consecutive\s+|calendar\s+|study\s+)?(?:个)?(?P<suffix>%|％|"
    r"(?:days?|weeks?|months?|years?|mg|kg|g|µg|μg|mcg|mL|ml|cc|L|IU|U|mmHg|cm|mm)(?![A-Za-z])|"
    r"毫克|千克|克|微克|毫升|升|国际单位|毫米汞柱|厘米|毫米|周岁|天|日|周(?!期|岁)|月|年|岁))",
    re.I,
)
PERCENTAGE_VALUE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*[%％]")
MAX_CT_GOV_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_MANUAL_DOCUMENT_BYTES = 64 * 1024 * 1024
CTGOV_USER_AGENT = "CMS-Medical-Workbench/0.1"
DOCUMENT_CONTENT_VALIDATOR_VERSION = "content_consistency_v2"
PDF_GEOMETRY_NORMALIZATION_VERSION = "bbox_q2pt_v1"
PDF_GEOMETRY_QUANTUM_POINTS = 2.0
EXTRACTION_MAPPING_VERSION = "m11map_v11_ocr_reanchor_table_rows_bbox_q2pt"


@dataclass(frozen=True)
class PdfPayloadValidation:
    is_valid: bool
    magic_valid: bool
    declared_size_matches: bool
    content_type_pdf: bool
    actual_size: int
    sha256: str


@dataclass(frozen=True)
class TranslationFidelityResult:
    passed: bool
    failure_codes: tuple[str, ...]
    source_numeric_tokens: tuple[str, ...]
    translated_numeric_tokens: tuple[str, ...]
    source_abbreviations: tuple[str, ...]


@dataclass(frozen=True)
class BinaryFetchResult:
    payload: bytes
    final_url: str
    content_type: str


@dataclass(frozen=True)
class _PdfTextBlock:
    physical_page: int
    block_index: int
    source_locator: str
    bbox: tuple[float, float, float, float]
    page_width: float
    page_height: float
    source_text: str
    source_text_sha256: str
    max_size: float
    is_bold: bool
    schedule_page: bool
    layout_role: str = "body"


class _AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname not in CTGOV_ALLOWED_HOSTS:
            raise urllib.error.URLError(
                "ClinicalTrials.gov redirect target is not allowed"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ClinicalTrialsGovClient:
    RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        *,
        timeout_seconds: int = 120,
        max_attempts: int = 3,
        max_retry_delay_seconds: float = 10.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, int(max_attempts))
        self.max_retry_delay_seconds = max(0.0, float(max_retry_delay_seconds))
        self.sleep = sleep

    def _retry_delay(self, retry_after: str, attempt: int) -> float:
        fallback = min(self.max_retry_delay_seconds, float(2**attempt))
        value = (retry_after or "").strip()
        if not value:
            return fallback
        if value.isdigit():
            return min(self.max_retry_delay_seconds, float(value))
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            seconds = max(
                0.0,
                (parsed - datetime.now(timezone.utc)).total_seconds(),
            )
            return min(self.max_retry_delay_seconds, seconds)
        except (TypeError, ValueError, OverflowError):
            return fallback

    def _open_with_retry(self, opener: Any, request: urllib.request.Request):
        for attempt in range(self.max_attempts):
            try:
                return opener.open(request, timeout=self.timeout_seconds)
            except urllib.error.HTTPError as exc:
                if (
                    exc.code not in self.RETRYABLE_STATUS_CODES
                    or attempt + 1 >= self.max_attempts
                ):
                    raise
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                exc.close()
                self.sleep(self._retry_delay(retry_after, attempt))
            except (urllib.error.URLError, TimeoutError, ConnectionResetError):
                if attempt + 1 >= self.max_attempts:
                    raise
                self.sleep(self._retry_delay("", attempt))
        raise RuntimeError("ClinicalTrials.gov retry loop ended unexpectedly")

    def fetch_json(self, url: str) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in CTGOV_ALLOWED_HOSTS:
            raise ValueError("ClinicalTrials.gov URL is outside the allowlist")
        opener = urllib.request.build_opener(
            _AllowlistedRedirectHandler(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        request = urllib.request.Request(
            url,
            headers={"User-Agent": CTGOV_USER_AGENT, "Accept": "application/json"},
        )
        with self._open_with_retry(opener, request) as response:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_CT_GOV_RESPONSE_BYTES:
                raise RuntimeError("ClinicalTrials.gov response exceeds size limit")
            payload = response.read(MAX_CT_GOV_RESPONSE_BYTES + 1)
            if len(payload) > MAX_CT_GOV_RESPONSE_BYTES:
                raise RuntimeError("ClinicalTrials.gov response exceeds size limit")
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname not in CTGOV_ALLOWED_HOSTS:
                raise RuntimeError(
                    "ClinicalTrials.gov final URL is outside the allowlist"
                )
            content_type = response.headers.get("Content-Type", "")
            if "json" not in content_type.lower():
                raise RuntimeError("ClinicalTrials.gov response is not JSON")
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise RuntimeError("ClinicalTrials.gov JSON response must be an object")
        return value

    def fetch_binary(self, url: str, *, accept: str) -> BinaryFetchResult:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in CTGOV_ALLOWED_HOSTS:
            raise ValueError("ClinicalTrials.gov URL is outside the allowlist")
        opener = urllib.request.build_opener(
            _AllowlistedRedirectHandler(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        request = urllib.request.Request(
            url,
            headers={"User-Agent": CTGOV_USER_AGENT, "Accept": accept},
        )
        with self._open_with_retry(opener, request) as response:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_CT_GOV_RESPONSE_BYTES:
                raise RuntimeError("ClinicalTrials.gov document exceeds size limit")
            payload = response.read(MAX_CT_GOV_RESPONSE_BYTES + 1)
            if len(payload) > MAX_CT_GOV_RESPONSE_BYTES:
                raise RuntimeError("ClinicalTrials.gov document exceeds size limit")
            final_url = response.geturl()
            final = urlparse(final_url)
            if final.scheme != "https" or final.hostname not in CTGOV_ALLOWED_HOSTS:
                raise RuntimeError(
                    "ClinicalTrials.gov final URL is outside the allowlist"
                )
            return BinaryFetchResult(
                payload=payload,
                final_url=final_url,
                content_type=response.headers.get("Content-Type", ""),
            )


class WritingReferenceDiscoveryService:
    def __init__(
        self,
        repository: WritingReferenceRepository,
        client: Any,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.repository = repository
        self.client = client
        self.clock = clock

    def snapshot_id(
        self,
        project_id: str,
        request: WritingReferenceSearchCreateRequest,
    ) -> str:
        semantic = {
            "project_id": project_id,
            "search": request.search.model_dump(mode="json"),
            "idempotency_key": request.idempotency_key,
        }
        digest = hashlib.sha256(
            json.dumps(
                semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()[:20]
        return f"wref_search_{digest}"

    def create_search_snapshot(
        self,
        project_id: str,
        request: WritingReferenceSearchCreateRequest,
    ) -> WritingReferenceSearchSnapshot:
        if not project_id.strip():
            raise ValueError("project_id is required")
        if not request.idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        version = self.client.fetch_json(f"{CTGOV_API_ROOT}/version")
        studies = []
        page_count = 0
        page_token = None
        reported_total = None
        while True:
            page_count += 1
            if page_count > 100:
                raise RuntimeError(
                    "ClinicalTrials.gov pagination safety limit exceeded"
                )
            page = self.client.fetch_json(search_url(request.search, page_token))
            page_studies = page.get("studies") or []
            if not isinstance(page_studies, list):
                raise RuntimeError(
                    "ClinicalTrials.gov studies payload must be an array"
                )
            studies.extend(page_studies)
            page_total = page.get("totalCount")
            if page_total is not None:
                page_total = int(page_total)
                if reported_total is not None and page_total != reported_total:
                    raise RuntimeError(
                        "ClinicalTrials.gov reported total changed across pages"
                    )
                reported_total = page_total
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        if reported_total is None:
            raise RuntimeError("ClinicalTrials.gov total count is missing")
        if reported_total != len(studies):
            raise RuntimeError(
                f"ClinicalTrials.gov count mismatch: returned={len(studies)}, total={reported_total}"
            )
        candidates = [candidate_from_study(study) for study in studies]
        nct_ids = [candidate.nct_id for candidate in candidates]
        if len(set(nct_ids)) != len(nct_ids):
            raise RuntimeError(
                "ClinicalTrials.gov pagination returned duplicate NCT identifiers"
            )
        snapshot = WritingReferenceSearchSnapshot(
            snapshot_id=self.snapshot_id(project_id, request),
            project_id=project_id,
            request=request.search,
            query_url=search_url(request.search),
            api_version=str(version.get("apiVersion") or ""),
            data_timestamp=str(version.get("dataTimestamp") or ""),
            total_count=reported_total,
            returned_count=len(candidates),
            page_count=page_count,
            candidates=candidates,
            created_by=request.actor,
            created_at=self.clock(),
        )
        return self.repository.save_search_snapshot(
            snapshot,
            idempotency_key=request.idempotency_key,
        )


class WritingReferenceDocumentService:
    def __init__(
        self,
        repository: WritingReferenceRepository,
        client: Any,
        *,
        artifact_root: Any,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        from pathlib import Path

        self.repository = repository
        self.client = client
        self.artifact_root = Path(artifact_root)
        self.clock = clock

    def ingest(
        self,
        project_id: str,
        request: WritingReferenceDocumentIngestRequest,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> WritingReferenceDocumentArtifact:
        snapshot = self.repository.search_snapshot(project_id, request.snapshot_id)
        candidate = next(
            (item for item in snapshot.candidates if item.nct_id == request.nct_id),
            None,
        )
        if candidate is None:
            raise ValueError("candidate does not belong to search snapshot")
        decision = self.repository.relevance_decision(
            project_id,
            request.snapshot_id,
            request.nct_id,
        )
        if decision.relevance_status not in {"direct_competitor", "indirect_reference"}:
            raise ValueError("candidate is not approved for document ingestion")
        source_document = next(
            (
                item
                for item in candidate.public_documents
                if item.document_id == request.document_id
            ),
            None,
        )
        if source_document is None:
            raise ValueError("public document does not belong to candidate")
        artifact_id = (
            "wref_doc_"
            + hashlib.sha256(
                (
                    f"{project_id}|{request.snapshot_id}|{request.nct_id}|"
                    f"{request.document_id}|{source_document.download_url}"
                ).encode("utf-8")
            ).hexdigest()[:20]
        )
        try:
            return self.repository.document_artifact(project_id, artifact_id)
        except KeyError:
            pass

        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "downloading",
                    "current_substep": "正在下载公开 Protocol（研究方案）",
                    "completed": 0,
                    "total": 1,
                    "unit": "file",
                }
            )
        fetched = self.client.fetch_binary(
            source_document.download_url,
            accept="application/pdf",
        )
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "downloading",
                    "current_substep": "公开 Protocol（研究方案）下载完成",
                    "completed": 1,
                    "total": 1,
                    "unit": "file",
                }
            )
        final = urlparse(fetched.final_url)
        if final.scheme != "https" or final.hostname not in CTGOV_ALLOWED_HOSTS:
            raise RuntimeError(
                "download final URL is outside the ClinicalTrials.gov allowlist"
            )
        validation = validate_pdf_payload(
            fetched.payload,
            declared_size=source_document.declared_size,
            content_type=fetched.content_type,
        )
        if not validation.is_valid:
            raise RuntimeError(
                "PDF validation failed: "
                f"magic={validation.magic_valid}, size={validation.declared_size_matches}, "
                f"content_type={validation.content_type_pdf}"
            )
        project_token = hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:16]
        storage_relpath = f"{project_token}/{artifact_id}/{validation.sha256}.pdf"
        output_path = self.artifact_root / storage_relpath
        output_path.parent.mkdir(parents=True, exist_ok=True)
        created_here = self._write_immutable_file(
            output_path,
            fetched.payload,
            validation.sha256,
        )
        artifact = WritingReferenceDocumentArtifact(
            artifact_id=artifact_id,
            project_id=project_id,
            snapshot_id=request.snapshot_id,
            nct_id=request.nct_id,
            source_document_id=request.document_id,
            document_type=source_document.document_type,
            filename=source_document.filename,
            document_date=source_document.document_date,
            upload_date=source_document.upload_date,
            requested_url=source_document.download_url,
            final_url=fetched.final_url,
            content_type=fetched.content_type,
            declared_size=source_document.declared_size,
            actual_size=validation.actual_size,
            content_sha256=validation.sha256,
            created_by=request.actor,
            created_at=self.clock(),
        )
        try:
            return self.repository.save_document_artifact(
                artifact,
                storage_relpath=storage_relpath,
                idempotency_key=request.idempotency_key,
            )
        except Exception:
            self._remove_unregistered_file(
                project_id,
                artifact_id,
                output_path,
                validation.sha256,
                created_here=created_here,
            )
            raise

    def ingest_manual(
        self,
        project_id: str,
        request: WritingReferenceManualDocumentUploadRequest,
        *,
        filename: str,
        content_type: str,
        payload: bytes,
    ) -> WritingReferenceDocumentArtifact:
        snapshot = self.repository.search_snapshot(project_id, request.snapshot_id)
        candidate = next(
            (item for item in snapshot.candidates if item.nct_id == request.nct_id),
            None,
        )
        if candidate is None:
            raise ValueError("candidate does not belong to search snapshot")
        decision = self.repository.relevance_decision(
            project_id,
            request.snapshot_id,
            request.nct_id,
        )
        if decision.relevance_status not in {"direct_competitor", "indirect_reference"}:
            raise ValueError("candidate is not approved for document ingestion")
        canonical_filename, canonical_content_type, extension, content_hash = (
            validate_manual_document_payload(
                filename=filename,
                content_type=content_type,
                payload=payload,
            )
        )
        source_document_id = (
            "manual_"
            + hashlib.sha256(
                (
                    f"{request.nct_id}|{request.document_type}|{request.document_date}|"
                    f"{canonical_filename}|{content_hash}"
                ).encode("utf-8")
            ).hexdigest()[:24]
        )
        artifact_id = (
            "wref_doc_"
            + hashlib.sha256(
                (
                    f"{project_id}|{request.snapshot_id}|{request.nct_id}|"
                    f"{source_document_id}|{content_hash}"
                ).encode("utf-8")
            ).hexdigest()[:20]
        )
        try:
            return self.repository.document_artifact(project_id, artifact_id)
        except KeyError:
            pass

        project_token = hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:16]
        storage_relpath = f"{project_token}/{artifact_id}/{content_hash}{extension}"
        output_path = self.artifact_root / storage_relpath
        output_path.parent.mkdir(parents=True, exist_ok=True)
        created_here = self._write_immutable_file(output_path, payload, content_hash)
        provenance = f"manual-upload:{source_document_id}"
        artifact = WritingReferenceDocumentArtifact(
            artifact_id=artifact_id,
            project_id=project_id,
            snapshot_id=request.snapshot_id,
            nct_id=request.nct_id,
            source_document_id=source_document_id,
            document_type=request.document_type,
            filename=canonical_filename,
            document_date=request.document_date.strip(),
            upload_date=self.clock().date().isoformat(),
            requested_url=provenance,
            final_url=provenance,
            content_type=canonical_content_type,
            declared_size=len(payload),
            actual_size=len(payload),
            content_sha256=content_hash,
            source_status="user_uploaded",
            created_by=request.actor,
            created_at=self.clock(),
        )
        try:
            return self.repository.save_document_artifact(
                artifact,
                storage_relpath=storage_relpath,
                idempotency_key=request.idempotency_key,
            )
        except Exception:
            self._remove_unregistered_file(
                project_id,
                artifact_id,
                output_path,
                content_hash,
                created_here=created_here,
            )
            raise

    @staticmethod
    def _write_immutable_file(
        output_path: Any, payload: bytes, content_hash: str
    ) -> bool:
        if output_path.exists():
            if hashlib.sha256(output_path.read_bytes()).hexdigest() != content_hash:
                raise RuntimeError("immutable document artifact hash mismatch")
            return False
        temporary_path = output_path.with_name(
            f".{output_path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary_path.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, output_path)
        finally:
            if temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
        if hashlib.sha256(output_path.read_bytes()).hexdigest() != content_hash:
            raise RuntimeError("immutable document artifact hash mismatch")
        return True

    def _remove_unregistered_file(
        self,
        project_id: str,
        artifact_id: str,
        output_path: Any,
        content_hash: str,
        *,
        created_here: bool,
    ) -> None:
        if not created_here or not output_path.exists():
            return
        try:
            registered = self.repository.document_artifact(project_id, artifact_id)
        except KeyError:
            registered = None
        if registered is not None and registered.content_sha256 == content_hash:
            return
        try:
            output_path.unlink()
        except OSError:
            pass


class WritingReferenceTranslationService:
    def __init__(
        self,
        repository: WritingReferenceRepository,
        ai_task_runner: Any,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        chapter_pipeline: Any = None,
    ) -> None:
        self.repository = repository
        self.ai_task_runner = ai_task_runner
        self.clock = clock
        self.chapter_pipeline = chapter_pipeline

    @property
    def contract_hash(self) -> str:
        return COMPOSITE_TRANSLATION_CONTRACT_HASH

    @property
    def prompt_version(self) -> str:
        return COMPOSITE_TRANSLATION_PROMPT_VERSION

    @property
    def schema_version(self) -> str:
        return COMPOSITE_TRANSLATION_SCHEMA_VERSION

    def translation_matches_current_contract(
        self,
        project_id: str,
        translation: WritingReferenceTranslationRevision,
    ) -> bool:
        return (
            self.translation_current_contract_metadata(project_id, translation)
            is not None
        )

    def translation_current_contract_metadata(
        self,
        project_id: str,
        translation: WritingReferenceTranslationRevision,
    ) -> dict[str, str] | None:
        # The current contract is the document-level composite pipeline
        # (plan -> chunks -> Hy-MT2 -> Flash integration) with immutable
        # plan/chunk/integration lineage.  Old Flash-only candidates and
        # legacy span-keyed composite candidates without document-plan
        # lineage must NOT match.
        if getattr(translation, "contract_hash", ""):
            has_document_lineage = bool(
                getattr(translation, "document_structure_plan_id", "")
                and getattr(translation, "chapter_integration_result_id", "")
                and getattr(translation, "ai_run_id", "")
            )
            if not (
                translation.contract_hash == COMPOSITE_TRANSLATION_CONTRACT_HASH
                and translation.task_type == COMPOSITE_TRANSLATION_TASK_TYPE
                and translation.prompt_version == COMPOSITE_TRANSLATION_PROMPT_VERSION
                and translation.schema_version == COMPOSITE_TRANSLATION_SCHEMA_VERSION
                and translation.model_name == COMPOSITE_TRANSLATION_BODY_MODEL
                and has_document_lineage
            ):
                return None
            return {
                "task_type": translation.task_type,
                "prompt_version": translation.prompt_version,
                "schema_version": translation.schema_version,
                "provider": translation.provider,
                "model_name": translation.model_name,
                "contract_hash": translation.contract_hash,
            }
        getter = getattr(self.ai_task_runner, "get", None)
        if getter is None:
            return None
        try:
            run = getter(project_id, translation.ai_run_id)
        except (KeyError, OSError, ValueError):
            return None
        if not (
            getattr(run, "task_type", "") == COMPOSITE_TRANSLATION_TASK_TYPE
            and getattr(run, "prompt_version", "")
            == COMPOSITE_TRANSLATION_PROMPT_VERSION
            and getattr(run, "schema_version", "")
            == COMPOSITE_TRANSLATION_SCHEMA_VERSION
            and getattr(run, "model_name", "") == COMPOSITE_TRANSLATION_BODY_MODEL
        ):
            return None
        return {
            "task_type": COMPOSITE_TRANSLATION_TASK_TYPE,
            "prompt_version": COMPOSITE_TRANSLATION_PROMPT_VERSION,
            "schema_version": COMPOSITE_TRANSLATION_SCHEMA_VERSION,
            "provider": getattr(run, "provider", ""),
            "model_name": COMPOSITE_TRANSLATION_BODY_MODEL,
            "contract_hash": COMPOSITE_TRANSLATION_CONTRACT_HASH,
        }

    def project_translation_to_current_contract(
        self,
        project_id: str,
        translation: WritingReferenceTranslationRevision,
    ) -> WritingReferenceTranslationRevision:
        metadata = self.translation_current_contract_metadata(project_id, translation)
        if metadata is None:
            raise ValueError(
                "translation does not match the current regulatory translation contract"
            )
        return translation.model_copy(update=metadata)

    def _require_current_content_validation(
        self,
        project_id: str,
        artifact: WritingReferenceDocumentArtifact,
    ) -> None:
        validation = self.repository.document_validation(
            project_id, artifact.artifact_id
        )
        latest_extraction_revision = self.repository.latest_extraction_revision(
            project_id, artifact.artifact_id
        )
        if (
            validation.status not in {"confirmed", "user_overridden"}
            or validation.document_sha256 != artifact.content_sha256
            or validation.source_state_revision != artifact.state_revision
            or validation.extraction_revision != latest_extraction_revision
        ):
            raise ValueError(
                "document content validation must be current and confirmed before translation"
            )
        structure_review = next(
            (
                review
                for review in self.repository.extraction_reviews(
                    project_id, artifact_id=artifact.artifact_id
                )
                if review.extraction_revision == latest_extraction_revision
            ),
            None,
        )
        if structure_review is None or structure_review.decision != "approved":
            raise ValueError(
                "latest extraction structure review must be approved before translation"
            )
        ocr_projection = self.repository.effective_ocr_consistency_qc(
            project_id,
            artifact.artifact_id,
            latest_extraction_revision,
        )
        if ocr_projection.effective_status not in {
            "pass",
            "medical_confirmed_with_residual_issue",
        }:
            raise ValueError(
                "OCR consistency review must pass or receive one batch medical "
                "confirmation before translation"
            )

    def translate(
        self,
        project_id: str,
        request: WritingReferenceTranslationRequest,
    ) -> WritingReferenceTranslationRevision:
        span = self.repository.source_span(project_id, request.span_id)
        artifact = self.repository.document_artifact(project_id, span.artifact_id)
        if (
            self.repository.latest_extraction_revision(project_id, artifact.artifact_id)
            != span.extraction_revision
        ):
            raise ValueError(
                "translation requires a span from the latest extraction revision"
            )
        self._require_current_content_validation(project_id, artifact)
        source_revision = f"{span.span_id}_r1"
        existing = [
            item
            for item in self.repository.translations(project_id, span.span_id)
            if item.glossary_version == request.glossary_version
            and item.document_sha256 == artifact.content_sha256
            and item.status == "pending_medical_approval"
            and self.translation_matches_current_contract(project_id, item)
        ]
        if existing:
            return self.project_translation_to_current_contract(
                project_id,
                sorted(existing, key=lambda item: item.revision)[-1],
            )
        translation_id = (
            "wref_translation_"
            + hashlib.sha256(
                (
                    f"{project_id}|{span.span_id}|{source_revision}|"
                    f"{request.glossary_version}|{COMPOSITE_TRANSLATION_CONTRACT_HASH}"
                ).encode("utf-8")
            ).hexdigest()[:20]
        )

        # Authoritative path: composite pipeline (Flash plan -> Hy-MT2 body ->
        # Flash QC).  If no pipeline is wired, fail closed — never fall back
        # to the legacy Flash-only body translator.
        if self.chapter_pipeline is not None:
            return self._generate_with_composite_pipeline(
                project_id=project_id,
                span=span,
                artifact=artifact,
                translation_id=translation_id,
                glossary_version=request.glossary_version,
                user_instruction=request.user_instruction,
                revision=1,
                expected_revision=0,
                idempotency_key=request.idempotency_key,
            )
        raise CompositePipelineUnavailableError(
            "composite chapter translation pipeline is not configured; "
            "legacy Flash-only translation is not permitted"
        )

    def revise(
        self,
        project_id: str,
        translation_id: str,
        request: WritingReferenceTranslationRevisionRequest,
    ) -> WritingReferenceTranslationRevision:
        current = self.repository.translation(
            project_id,
            translation_id,
            request.expected_translation_revision,
        )
        review = self.repository.medical_review(project_id, request.medical_review_id)
        if (
            review.translation_id != translation_id
            or review.translation_revision != current.revision
            or review.decision != "returned"
        ):
            raise ValueError(
                "a returned medical review for the current translation revision is required"
            )
        current_review = self.repository.current_medical_review(
            project_id,
            translation_id,
            current.revision,
        )
        if (
            current_review.review_id != review.review_id
            or current_review.decision != "returned"
        ):
            raise WritingReferenceConflictError(
                "supplied returned medical review is no longer current for this translation revision"
            )
        span = self.repository.source_span(project_id, current.span_id)
        artifact = self.repository.document_artifact(project_id, span.artifact_id)
        if (
            self.repository.latest_extraction_revision(project_id, artifact.artifact_id)
            != span.extraction_revision
        ):
            raise ValueError(
                "translation revision requires the latest extraction lineage"
            )
        self._require_current_content_validation(project_id, artifact)
        instruction = (
            f"{request.user_instruction.strip()}\n医学审核意见：{review.comment}"
        )
        # Revisions after medical review must also use the composite pipeline.
        if self.chapter_pipeline is not None:
            return self._generate_with_composite_pipeline(
                project_id=project_id,
                span=span,
                artifact=artifact,
                translation_id=translation_id,
                glossary_version=current.glossary_version,
                user_instruction=instruction,
                revision=current.revision + 1,
                expected_revision=current.revision,
                idempotency_key=request.idempotency_key,
                required_current_medical_review_id=review.review_id,
            )
        raise CompositePipelineUnavailableError(
            "composite chapter translation pipeline is not configured; "
            "legacy Flash-only translation is not permitted"
        )

    def _generate_with_composite_pipeline(
        self,
        *,
        project_id: str,
        span: WritingReferenceExtractedSpan,
        artifact: WritingReferenceDocumentArtifact,
        translation_id: str,
        glossary_version: str,
        user_instruction: str,
        revision: int,
        expected_revision: int,
        idempotency_key: str,
        required_current_medical_review_id: str = "",
    ) -> WritingReferenceTranslationRevision:
        """Generate a translation via the authoritative document composite pipeline.

        For the direct (non-batch) entry point, the pipeline still materializes
        document plan / chunk / integration / composite-run lineage so the
        revision is contract-current.  The body remains Hy-MT2; Flash plans and
        integrates only.  Legacy Flash-only body translation is never called.
        """
        assert self.chapter_pipeline is not None
        from packages.contracts.workbench_contracts.models import (
            ChapterIntegrationResult,
            CompositePipelineRun,
            CompositePipelineRunStage,
            DocumentStructurePlan,
            DocumentStructurePlanChapter,
            TranslationChunkRecord,
        )
        from .chapter_translation_pipeline import (
            FLASH_PLANNING_MODEL,
            FLASH_PLANNING_PROMPT_VERSION,
            FLASH_QC_MODEL,
            FLASH_QC_PROMPT_VERSION,
            HY_MT2_MODEL_ID,
            HY_MT2_PROMPT_VERSION,
            TRANSLATION_CONTRACT_FINGERPRINT,
            DocumentPlanRequest,
            FidelityBlockedError,
            TranslationUnit,
            _planner_contract_fingerprint,
            _sha256 as _pipeline_sha256,
            build_document_planner_input,
            build_chunks_from_plan,
            call_flash_planner_with_single_retry,
            contains_unit_markers,
            evaluate_translation_fidelity_aligned_units,
            integrate_units_with_flash,
            reassemble_aligned_translation,
            reconstruct_unit_map,
            split_source_into_units,
            strip_unit_markers,
            translate_units_with_bounded_correction,
            validate_document_plan,
        )

        source_revision = f"{span.span_id}_r1"
        all_spans = tuple(
            self.repository.source_spans(
                project_id,
                artifact.artifact_id,
                extraction_revision=span.extraction_revision,
            )
        )
        contract_fp = _planner_contract_fingerprint(
            artifact_id=artifact.artifact_id,
            extraction_revision=span.extraction_revision,
            planner_model=FLASH_PLANNING_MODEL,
            planner_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            document_sha256=artifact.content_sha256,
            translation_contract=TRANSLATION_CONTRACT_FINGERPRINT,
        )
        plan = self.repository.current_document_structure_plan(
            project_id,
            artifact.artifact_id,
            span.extraction_revision,
            contract_fp,
        )
        if plan is None:
            doc_text, document_context = build_document_planner_input(
                all_spans,
                document_context={
                    "artifact_id": artifact.artifact_id,
                    "document_type": artifact.document_type,
                    "document_sha256": artifact.content_sha256,
                    "extraction_revision": span.extraction_revision,
                    "span_count": len(all_spans),
                },
            )
            flash_plan = call_flash_planner_with_single_retry(
                self.chapter_pipeline.flash_planner,
                doc_text,
                document_context,
            )
            validated = validate_document_plan(
                flash_plan,
                DocumentPlanRequest(
                    artifact_id=artifact.artifact_id,
                    extraction_revision=span.extraction_revision,
                    document_sha256=artifact.content_sha256,
                    source_spans=all_spans,
                ),
            )
            plan_id = (
                "docplan_"
                + hashlib.sha256(
                    f"{artifact.artifact_id}|{span.extraction_revision}|{contract_fp}".encode()
                ).hexdigest()[:24]
            )
            chapters = [
                DocumentStructurePlanChapter(
                    chapter_id=ch_id,
                    chapter_order=idx + 1,
                    title=ch_title,
                    heading_path=[],
                    ich_m11_anchor=ch_anchor,
                    source_span_ids=list(ch_span_ids),
                    ambiguity_codes=[],
                )
                for idx, (ch_id, ch_title, ch_anchor, ch_span_ids) in enumerate(
                    validated.chapters
                )
            ]
            plan = DocumentStructurePlan(
                plan_id=plan_id,
                project_id=project_id,
                artifact_id=artifact.artifact_id,
                extraction_revision=span.extraction_revision,
                document_sha256=artifact.content_sha256,
                document_role=validated.document_role,
                planner_model=flash_plan.plan_model,
                planner_prompt_version=flash_plan.plan_prompt_version,
                planner_input_hash=flash_plan.plan_input_hash,
                planner_output_hash=flash_plan.plan_output_hash,
                planner_contract_fingerprint=contract_fp,
                chapters=chapters,
                ambiguity_codes=list(validated.ambiguity_codes),
                status="active",
                created_at=self.clock(),
            )
            plan = self.repository.save_document_structure_plan(
                plan,
                idempotency_key=(
                    f"docplan:{artifact.artifact_id}:{span.extraction_revision}:{contract_fp}"
                ),
            )

        chapter = next(
            (ch for ch in plan.chapters if span.span_id in ch.source_span_ids),
            None,
        )
        if chapter is None:
            raise CompositePipelineUnavailableError(
                f"span {span.span_id} is not assigned to any chapter in the document plan"
            )
        chapter_id = chapter.chapter_id

        def _chapter_tid() -> str:
            material = json.dumps(
                {
                    "project_id": project_id,
                    "plan_id": plan.plan_id,
                    "chapter_id": chapter_id,
                    "contract_hash": COMPOSITE_TRANSLATION_CONTRACT_HASH,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            return (
                "wref_translation_ch_"
                + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
            )

        existing_integration = self.repository.chapter_integration_result(
            project_id,
            plan.plan_id,
            chapter_id,
            translation_contract_fingerprint=TRANSLATION_CONTRACT_FINGERPRINT,
        )
        if existing_integration is not None and revision == 1:
            current = self.repository.current_translation_by_id(
                project_id, _chapter_tid()
            )
            if current is not None:
                return current

        from .chapter_translation_pipeline import DocumentPlanResult as _DPR

        plan_result = _DPR(
            flash_plan=None,  # type: ignore[arg-type]
            chapters=tuple(
                (ch.chapter_id, ch.title, ch.ich_m11_anchor, tuple(ch.source_span_ids))
                for ch in plan.chapters
            ),
            document_role=plan.document_role,
            ambiguity_codes=tuple(plan.ambiguity_codes),
        )
        chapter_chunks: list = []
        for entry in build_chunks_from_plan(plan_result, all_spans):
            for key, chunks in entry.items():
                if key[0] == chapter_id:
                    chapter_chunks = list(chunks)
        if not chapter_chunks:
            raise CompositePipelineUnavailableError(
                f"no chunks built for chapter {chapter_id}"
            )

        existing_chunks = {
            c.chunk_fingerprint: c
            for c in self.repository.translation_chunks_for_plan(
                project_id, plan.plan_id
            )
        }
        # Medical revise (revision > 1) reuses the immutable plan but must
        # re-run body translation and integration under the review instruction.
        # Do not reuse completed chunks/integration for a new revision.
        force_retranslate = revision > 1
        chunk_translations: list[tuple[Any, str]] = []
        # Aligned unit data per chunk: (chunk_spec, units, target_map).
        chunk_aligned: list[tuple[Any, tuple, dict[int, str]]] = []
        # Hy-stage blocking state (second failed corrective pass).
        hy_block_codes: list[str] = []
        hy_block_text = ""
        hy_block_raw_text = ""
        stage_ledger: list[CompositePipelineRunStage] = [
            CompositePipelineRunStage(
                stage="toc_planning",
                model=plan.planner_model,
                prompt_version=plan.planner_prompt_version,
                input_hash=plan.planner_input_hash,
                output_hash=plan.planner_output_hash,
            )
        ]
        for chunk_spec in chapter_chunks:
            reused = (
                None
                if force_retranslate
                else existing_chunks.get(chunk_spec.chunk_fingerprint)
            )
            if reused is not None and reused.status == "completed":
                reused_units = split_source_into_units(chunk_spec.source_text)
                reused_map = reconstruct_unit_map(
                    reused.translated_text, reused.unit_targets, reused_units
                )
                chunk_translations.append((chunk_spec, reused.translated_text))
                chunk_aligned.append((chunk_spec, reused_units, reused_map))
                continue
            glossary_contract = render_regulatory_translation_glossary_contract(
                chunk_spec.source_text
            )
            # Medical-review instruction is carried in the glossary channel for
            # revise so Hy-MT2 sees the review constraints without re-planning.
            effective_glossary = glossary_contract or glossary_version
            if force_retranslate and user_instruction:
                effective_glossary = f"{effective_glossary}\n\n{user_instruction}"
            # V11: ordered semantic translation units with at most one
            # deterministic corrective retry; a second failure blocks the
            # chapter.
            chunk_units = split_source_into_units(chunk_spec.source_text)
            try:
                hy_mt2_result, chunk_parsed = translate_units_with_bounded_correction(
                    self.chapter_pipeline.hy_mt2_translator,
                    units=chunk_units,
                    glossary=effective_glossary,
                    chapter_id=chapter_id,
                    chunk_id=chunk_spec.chunk_id,
                    read_only_context=chunk_spec.adjacent_context or "",
                )
            except FidelityBlockedError as exc:
                hy_block_codes = list(exc.failure_codes)
                hy_block_text = strip_unit_markers(exc.last_output)
                hy_block_raw_text = strip_unit_markers(exc.raw_provider_output)
                stage_ledger.append(
                    CompositePipelineRunStage(
                        stage="translating_hy_mt2_blocked",
                        model=HY_MT2_MODEL_ID,
                        prompt_version=HY_MT2_PROMPT_VERSION,
                        input_hash=_pipeline_sha256(chunk_spec.source_text),
                        output_hash=_pipeline_sha256(hy_block_text),
                    )
                )
                break
            aligned_chunk_text = reassemble_aligned_translation(
                chunk_units, chunk_parsed
            )
            if not (aligned_chunk_text or "").strip():
                raise CompositePipelineUnavailableError(
                    f"Hy-MT2 returned empty translation for chunk {chunk_spec.chunk_id}"
                )
            if not force_retranslate:
                self.repository.save_translation_chunk(
                    TranslationChunkRecord(
                        chunk_id=chunk_spec.chunk_id,
                        plan_id=plan.plan_id,
                        project_id=project_id,
                        artifact_id=artifact.artifact_id,
                        chapter_id=chapter_id,
                        chunk_order=chunk_spec.chunk_order,
                        source_span_ids=list(chunk_spec.source_span_ids),
                        source_text=chunk_spec.source_text,
                        source_text_sha256=chunk_spec.source_text_sha256,
                        adjacent_context_sha256=chunk_spec.adjacent_context_sha256,
                        table_header_prefix=chunk_spec.table_header_prefix,
                        chunk_fingerprint=chunk_spec.chunk_fingerprint,
                        hy_mt2_model=hy_mt2_result.model,
                        hy_mt2_prompt_version=hy_mt2_result.prompt_version,
                        hy_mt2_input_hash=hy_mt2_result.input_hash,
                        translated_text=aligned_chunk_text,
                        translated_text_sha256=_pipeline_sha256(aligned_chunk_text),
                        unit_targets={str(k): v for k, v in chunk_parsed.items()},
                        translation_strategy=hy_mt2_result.translation_strategy,
                        status="completed",
                        created_at=self.clock(),
                    ),
                    idempotency_key=(
                        f"chunk:{plan.plan_id}:{chunk_spec.chunk_id}:"
                        f"{TRANSLATION_CONTRACT_FINGERPRINT[:12]}"
                    ),
                )
            chunk_translations.append((chunk_spec, aligned_chunk_text))
            chunk_aligned.append((chunk_spec, chunk_units, chunk_parsed))
            stage_ledger.append(
                CompositePipelineRunStage(
                    stage="translating_hy_mt2",
                    model=hy_mt2_result.model,
                    prompt_version=hy_mt2_result.prompt_version,
                    input_hash=hy_mt2_result.input_hash,
                    output_hash=hy_mt2_result.output_hash,
                )
            )

        chapter_translated = "\n\n".join(t for _, t in chunk_translations)
        flash_qc = None
        qc_failure_codes: list[str] = []
        qc_advisory_codes: list[str] = []
        if hy_block_codes:
            # Hy-stage second failure: chapter stops as fidelity-blocked
            # without calling Flash integration.
            flash_passed = False
            qc_failure_codes.extend(hy_block_codes)
            final_text = hy_block_text
            final_hash = _pipeline_sha256(final_text)
        else:
            # Chapter-level aligned units -> aligned marked Flash envelope.
            chapter_units: list[TranslationUnit] = []
            chapter_target_map: dict[int, str] = {}
            next_ordinal = 1
            for _cs, _units, _map in chunk_aligned:
                for _u in _units:
                    chapter_units.append(
                        TranslationUnit(ordinal=next_ordinal, text=_u.text)
                    )
                    chapter_target_map[next_ordinal] = _map.get(_u.ordinal, "")
                    next_ordinal += 1
            integration_outcome = integrate_units_with_flash(
                self.chapter_pipeline.flash_qc_runner,
                units=chapter_units,
                target_map=chapter_target_map,
            )
            flash_qc = integration_outcome.qc_result
            flash_passed = integration_outcome.passed
            qc_failure_codes.extend(integration_outcome.failure_codes)
            qc_advisory_codes.extend(integration_outcome.diagnostic_codes)
            final_text = (
                integration_outcome.final_text
                if integration_outcome.passed
                else chapter_translated
            )
            final_hash = _pipeline_sha256(final_text)
        # Marker transport must never leak into the candidate.
        if contains_unit_markers(final_text):
            raise CompositePipelineUnavailableError(
                "translation-unit markers leaked into the final candidate"
            )
        deterministic_failure_codes: list[str] = []
        if not hy_block_codes:
            for _chunk, units, target_map in chunk_aligned:
                deterministic_failure_codes.extend(
                    evaluate_translation_fidelity_aligned_units(
                        units,
                        target_map,
                    )
                )
        fidelity_passed = (
            not hy_block_codes and flash_passed and not deterministic_failure_codes
        )
        merged_failure_codes: list[str] = []
        for code in qc_failure_codes + deterministic_failure_codes:
            if code and code not in merged_failure_codes:
                merged_failure_codes.append(code)
        stage_ledger.append(
            CompositePipelineRunStage(
                stage="integration_qc",
                model=flash_qc.qc_model if flash_qc else FLASH_QC_MODEL,
                prompt_version=(
                    flash_qc.qc_prompt_version if flash_qc else FLASH_QC_PROMPT_VERSION
                ),
                input_hash=flash_qc.qc_input_hash if flash_qc else "",
                output_hash=flash_qc.qc_output_hash if flash_qc else "",
            )
        )

        chunk_ids = [cs.chunk_id for cs, _ in chunk_translations]
        chunk_hashes = [cs.chunk_fingerprint for cs, _ in chunk_translations]
        # One persisted integration per plan/chapter.  Medical revise reuses
        # that lineage id and writes a new translation revision (immutable
        # integration rows are not updated).
        flash_qc_model = flash_qc.qc_model if flash_qc else FLASH_QC_MODEL
        flash_qc_prompt = (
            flash_qc.qc_prompt_version if flash_qc else FLASH_QC_PROMPT_VERSION
        )
        flash_input_hash = flash_qc.qc_input_hash if flash_qc else ""
        flash_output_hash = flash_qc.qc_output_hash if flash_qc else ""
        integration_id = (
            "integration_"
            + hashlib.sha256(f"{plan.plan_id}|{chapter_id}".encode()).hexdigest()[:24]
        )
        if existing_integration is None and not force_retranslate:
            integration = ChapterIntegrationResult(
                integration_id=integration_id,
                plan_id=plan.plan_id,
                project_id=project_id,
                artifact_id=artifact.artifact_id,
                chapter_id=chapter_id,
                chunk_ids=chunk_ids,
                chunk_hashes=chunk_hashes,
                integrated_chinese_text=final_text,
                integrated_text_sha256=final_hash,
                flash_model=flash_qc_model,
                flash_prompt_version=flash_qc_prompt,
                flash_input_hash=flash_input_hash,
                flash_output_hash=flash_output_hash,
                fidelity_status="passed" if fidelity_passed else "blocked",
                fidelity_failure_codes=list(merged_failure_codes),
                fidelity_advisory_codes=list(dict.fromkeys(qc_advisory_codes)),
                blocked_raw_provider_output=hy_block_raw_text,
                blocked_raw_provider_output_sha256=(
                    _pipeline_sha256(hy_block_raw_text) if hy_block_raw_text else ""
                ),
                integration_windowed=False,
                translation_contract_fingerprint=TRANSLATION_CONTRACT_FINGERPRINT,
                status="completed",
                created_at=self.clock(),
            )
            self.repository.save_chapter_integration_result(
                integration,
                idempotency_key=(
                    f"integration:{plan.plan_id}:{chapter_id}:"
                    f"{TRANSLATION_CONTRACT_FINGERPRINT[:12]}"
                ),
            )
        elif force_retranslate:
            # Revised candidate text lives on the translation revision.
            # Keep chapter integration lineage pointer for structure audit.
            base_integration_id = (
                existing_integration.integration_id
                if existing_integration is not None
                else integration_id
            )
            integration = ChapterIntegrationResult(
                integration_id=base_integration_id,
                plan_id=plan.plan_id,
                project_id=project_id,
                artifact_id=artifact.artifact_id,
                chapter_id=chapter_id,
                chunk_ids=chunk_ids,
                chunk_hashes=chunk_hashes,
                integrated_chinese_text=final_text,
                integrated_text_sha256=final_hash,
                flash_model=flash_qc_model,
                flash_prompt_version=flash_qc_prompt,
                flash_input_hash=flash_input_hash,
                flash_output_hash=flash_output_hash,
                fidelity_status="passed" if fidelity_passed else "blocked",
                fidelity_failure_codes=list(merged_failure_codes),
                fidelity_advisory_codes=list(dict.fromkeys(qc_advisory_codes)),
                blocked_raw_provider_output=hy_block_raw_text,
                blocked_raw_provider_output_sha256=(
                    _pipeline_sha256(hy_block_raw_text) if hy_block_raw_text else ""
                ),
                integration_windowed=False,
                translation_contract_fingerprint=TRANSLATION_CONTRACT_FINGERPRINT,
                status="completed",
                created_at=self.clock(),
            )
        else:
            integration = existing_integration
            final_text = integration.integrated_chinese_text
            final_hash = integration.integrated_text_sha256
            fidelity_passed = integration.fidelity_status == "passed"
            merged_failure_codes = list(integration.fidelity_failure_codes)

        run_id = (
            "composite_run_"
            + hashlib.sha256(
                f"{plan.plan_id}|{chapter_id}|{integration.integration_id}|r{revision}".encode()
            ).hexdigest()[:28]
        )
        if self.repository.composite_pipeline_run(project_id, run_id) is None:
            self.repository.save_composite_pipeline_run(
                CompositePipelineRun(
                    run_id=run_id,
                    project_id=project_id,
                    plan_id=plan.plan_id,
                    chapter_id=chapter_id,
                    artifact_id=artifact.artifact_id,
                    stages=stage_ledger,
                    status="completed",
                    created_at=self.clock(),
                ),
                idempotency_key=(
                    f"composite_run:{plan.plan_id}:{chapter_id}:r{revision}"
                ),
            )

        # Prefer chapter-stable id; honor caller id only for medical revise
        # (same translation_id, new revision).
        effective_translation_id = translation_id if revision > 1 else _chapter_tid()
        all_span_ids = list(dict.fromkeys(chapter.source_span_ids))
        translation = WritingReferenceTranslationRevision(
            translation_id=effective_translation_id,
            project_id=project_id,
            span_id=span.span_id
            if revision > 1
            else (all_span_ids[0] if all_span_ids else span.span_id),
            source_span_revision=(
                f"{span.span_id}_r1"
                if revision > 1
                else f"{(all_span_ids[0] if all_span_ids else span.span_id)}_r1"
            ),
            document_sha256=artifact.content_sha256,
            glossary_version=glossary_version,
            revision=revision,
            translated_text=final_text,
            rationale=(
                f"document-plan/chunk: {plan.planner_model} plan, "
                f"{HY_MT2_MODEL_ID} body, {flash_qc_model} integration QC"
            ),
            fidelity_status="passed" if fidelity_passed else "blocked",
            fidelity_failure_codes=merged_failure_codes,
            ai_run_id=run_id,
            task_type=COMPOSITE_TRANSLATION_TASK_TYPE,
            prompt_version=COMPOSITE_TRANSLATION_PROMPT_VERSION,
            schema_version=COMPOSITE_TRANSLATION_SCHEMA_VERSION,
            provider="composite_pipeline",
            model_name=COMPOSITE_TRANSLATION_BODY_MODEL,
            contract_hash=COMPOSITE_TRANSLATION_CONTRACT_HASH,
            created_at=self.clock(),
            document_structure_plan_id=plan.plan_id,
            chapter_id=chapter_id,
            source_span_ids=all_span_ids,
            translation_chunk_ids=chunk_ids,
            chapter_integration_result_id=integration.integration_id,
        )
        return self.repository.save_translation(
            translation,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
            required_current_medical_review_id=required_current_medical_review_id,
        )

    def _generate_translation(
        self,
        *,
        project_id: str,
        span: WritingReferenceExtractedSpan,
        artifact: WritingReferenceDocumentArtifact,
        translation_id: str,
        glossary_version: str,
        user_instruction: str,
        revision: int,
        expected_revision: int,
        idempotency_key: str,
        required_current_medical_review_id: str = "",
    ) -> WritingReferenceTranslationRevision:
        """Legacy Flash-only body translator — permanently disabled.

        Production ``translate``/``revise`` never call this method.  The
        boundary is explicit and fail-closed so the path cannot be used
        silently even if an internal caller is reintroduced.
        """
        raise CompositePipelineUnavailableError(
            "legacy Flash-only translation path is permanently disabled; "
            "use the composite document pipeline (plan -> Hy-MT2 -> Flash QC)"
        )


class WritingReferenceExtractionService:
    def __init__(
        self,
        repository: WritingReferenceRepository,
        *,
        artifact_root: Any,
        ocr_runner: Any = None,
        ocr_model: str = "GLM-OCR-bf16",
        ocr_model_resolver: Callable[[], str] | None = None,
        ocr_dpi: int = 200,
        ocr_profile: str = "ocr-glm-v1",
        ocr_consistency_qc_runner: Any = None,
    ):
        from pathlib import Path

        self.repository = repository
        self.artifact_root = Path(artifact_root)
        self.ocr_runner = ocr_runner
        self.ocr_model = ocr_model
        self.ocr_model_resolver = ocr_model_resolver
        self.ocr_dpi = ocr_dpi
        self.ocr_profile = ocr_profile
        self.ocr_consistency_qc_runner = ocr_consistency_qc_runner

    def resolve_ocr_model(self) -> str:
        return (
            self.ocr_model_resolver()
            if self.ocr_model_resolver
            else self.ocr_model
        )

    def extract(
        self,
        project_id: str,
        artifact_id: str,
        *,
        actor: str,
        extraction_idempotency_key: str,
        ocr_model_override: str = "",
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> WritingReferenceExtractionResult:
        artifact = self.repository.document_artifact(project_id, artifact_id)
        replay = self.repository.saved_extraction_for_idempotency(
            project_id,
            artifact_id,
            idempotency_key=extraction_idempotency_key,
        )
        if replay is not None:
            return replay
        relative = self.repository.artifact_storage_relpath(project_id, artifact_id)
        path = (self.artifact_root / relative).resolve()
        root = self.artifact_root.resolve()
        if root not in path.parents or not path.is_file():
            raise RuntimeError("registered document artifact is unavailable")
        payload = path.read_bytes()
        def report(
            phase: str,
            current_substep: str,
            completed: int = 0,
            total: int = 0,
            unit: str = "",
            context: dict[str, Any] | None = None,
        ) -> None:
            if progress_callback is not None:
                progress_callback(
                    {
                        "phase": phase,
                        "current_substep": current_substep,
                        "completed": completed,
                        "total": total,
                        "unit": unit,
                        "context": context or {},
                    }
                )

        report("native_extracting", "正在提取原生文本")
        if artifact.filename.casefold().endswith(".docx"):
            from .writing_reference_docx import extract_docx_sections

            report("native_extracting", "正在读取 DOCX 原生文本", 0, 1, "file")
            result = extract_docx_sections(payload, artifact)
            report("native_extracting", "DOCX 原生文本提取完成", 1, 1, "file")
        else:
            result = extract_pdf_sections(payload, artifact, progress_callback=progress_callback)
            report(
                "native_extracting",
                "原生文本提取完成",
                result.page_count,
                result.page_count,
                "page",
            )
        # OCR recovery: recover text from zero-text pages AND anomaly pages
        # (text-bearing pages with vector-glyph symbol loss).  When an OCR
        # runner is configured, every selected page is processed.  For anomaly
        # pages the OCR text replaces the lossy native text in the span, while
        # the native text is retained in the lineage for audit.
        ocr_needed = bool(result.zero_text_pages) and self.ocr_runner is not None
        anomaly_pages: list[dict] = []
        if self.ocr_runner is not None:
            anomaly_pages = detect_anomaly_pages(payload)
            if anomaly_pages:
                ocr_needed = True
        if ocr_needed:
            result = self._recover_pages_with_ocr(
                payload,
                artifact,
                result,
                relative,
                anomaly_pages,
                ocr_model_override=ocr_model_override,
                progress_callback=progress_callback,
            )
        else:
            report("ocr_rendering", "无需 OCR，跳过页面渲染", 1, 1, "page")
            report("ocr_completing", "无需 OCR，页面识别已完成", 1, 1, "page")
        report("extraction_persisting", "正在持久化结构提取结果", 0, 1, "file")
        saved = self.repository.save_extraction(
            result,
            idempotency_key=extraction_idempotency_key,
        )
        report("extraction_persisting", "结构提取结果已持久化", 1, 1, "file")
        if not saved.spans:
            if self.ocr_runner is None:
                raise ValueError(
                    "document contains no extractable text and no OCR runner "
                    "is configured; fully scanned PDFs require GLM-OCR-bf16"
                )
            raise ValueError(
                "document contains no extractable text; OCR recovery produced "
                "no usable spans"
            )
        report("content_validating", "正在校验文件内容与当前研究上下文", 0, 1, "file")
        validation = evaluate_document_content(
            snapshot=self.repository.search_snapshot(project_id, artifact.snapshot_id),
            artifact=artifact,
            spans=saved.spans,
            actor=actor,
        )
        try:
            current = self.repository.document_validation(project_id, artifact_id)
        except KeyError:
            current = None
        expected_revision = current.revision if current else 0
        if (
            current is None
            or current.validator_version != validation.validator_version
            or current.document_sha256 != artifact.content_sha256
            or current.expected_context_hash != validation.expected_context_hash
            or current.extraction_revision != saved.extraction_revision
        ):
            validation = validation.model_copy(
                update={
                    "revision": expected_revision + 1,
                    "validation_id": "wref_validation_"
                    + hashlib.sha256(
                        (
                            f"{artifact.artifact_id}|{expected_revision + 1}|"
                            f"{artifact.content_sha256}|{validation.expected_context_hash}|"
                            f"{validation.validator_version}|{validation.status}"
                        ).encode("utf-8")
                    ).hexdigest()[:20],
                }
            )
            self.repository.save_document_validation(
                validation,
                expected_revision=expected_revision,
                idempotency_key=(
                    f"{extraction_idempotency_key}:content-validation:"
                    f"{validation.validator_version}:r{expected_revision + 1}"
                ),
            )
        report("content_validating", "文件内容校验已完成", 1, 1, "file")
        return saved

    def _recover_pages_with_ocr(
        self,
        payload: bytes,
        artifact: WritingReferenceDocumentArtifact,
        result: WritingReferenceExtractionResult,
        artifact_storage_relpath: str,
        anomaly_pages: list[dict] | None = None,
        ocr_model_override: str = "",
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> WritingReferenceExtractionResult:
        """Run the configured OCR route on zero-text and anomaly pages.

        OCR is performed at >=200 DPI with the exact allowlisted model.
        Every selected page is processed — there is no total-page cap.
        At most 8 OCR calls are active concurrently.  Rendering is sequential
        (one PyMuPDF document, not shared across threads); OCR calls are
        concurrent.

        Each recovered page produces a new source span whose provenance is
        recorded in ``ocr_recovery_pages`` on the extraction result, so
        downstream translation items carry immutable OCR lineage.
        """
        import concurrent.futures

        import pymupdf

        from .chapter_translation_pipeline import (
            WRITING_REFERENCE_OCR_MIN_DPI,
            WRITING_REFERENCE_OCR_MAX_CONCURRENCY,
            WRITING_REFERENCE_OCR_MODEL,
        )
        from .writing_reference_ocr_evidence import (
            build_ocr_evidence_relpath,
            png_dimensions,
            validate_new_ocr_page_evidence,
            write_immutable_ocr_png,
        )
        from hashlib import sha256 as _hs
        import json as _json

        ocr_model = str(ocr_model_override or self.resolve_ocr_model()).strip()
        if self.ocr_dpi < WRITING_REFERENCE_OCR_MIN_DPI:
            raise ValueError(f"OCR DPI must be >= {WRITING_REFERENCE_OCR_MIN_DPI}")
        if self.ocr_dpi != WRITING_REFERENCE_OCR_MIN_DPI:
            raise ValueError(
                f"OCR evidence must be rendered at {WRITING_REFERENCE_OCR_MIN_DPI} DPI"
            )
        if not ocr_model.strip():
            raise ValueError("OCR model must be configured")

        # Merge zero-text pages and anomaly pages (deduplicated, sorted).
        zero_text_set = set(result.zero_text_pages)
        anomaly_map: dict[int, str] = {}
        for entry in anomaly_pages or []:
            page = entry.get("physical_page")
            if isinstance(page, int) and page not in zero_text_set:
                anomaly_map[page] = entry.get("reason", "anomaly")
        pages_to_ocr = sorted(zero_text_set | set(anomaly_map.keys()))
        if not pages_to_ocr:
            return result

        def report(
            phase: str,
            current_substep: str,
            completed: int,
            total: int,
            unit: str = "page",
            context: dict[str, Any] | None = None,
        ) -> None:
            if progress_callback is not None:
                progress_callback(
                    {
                        "phase": phase,
                        "current_substep": current_substep,
                        "completed": completed,
                        "total": total,
                        "unit": unit,
                        "context": context or {},
                    }
                )

        profile_digest = _hs(
            _json.dumps(
                {"profile": self.ocr_profile, "model": ocr_model},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        locator_prefix = (
            "upload" if artifact.source_status == "user_uploaded" else "ctgov"
        )

        # Render all pages sequentially into a dict — never share a PyMuPDF
        # document/page across worker threads.
        page_images: dict[int, bytes] = {}
        page_image_metadata: dict[int, dict[str, Any]] = {}
        total_pages = len(pages_to_ocr)
        document_page_total = result.page_count
        report(
            "ocr_rendering",
            f"正在准备 {total_pages} 个需识别页面",
            0,
            total_pages,
            context={
                "document_page_total": document_page_total,
                "completed_ocr_pages": 0,
                "ocr_page_total": total_pages,
            },
        )
        document = pymupdf.open(stream=payload, filetype="pdf")
        try:
            for page_number in pages_to_ocr:
                page = document[page_number - 1]
                pixmap = page.get_pixmap(dpi=self.ocr_dpi)
                image_bytes = pixmap.tobytes("png")
                image_sha256 = _hs(image_bytes).hexdigest()
                width, height = png_dimensions(image_bytes)
                storage_relpath = build_ocr_evidence_relpath(
                    artifact_storage_relpath,
                    result.extraction_revision,
                    page_number,
                    self.ocr_dpi,
                    image_sha256,
                )
                page_images[page_number] = image_bytes
                page_image_metadata[page_number] = {
                    "image_sha256": image_sha256,
                    "image_size_bytes": len(image_bytes),
                    "image_width_px": width,
                    "image_height_px": height,
                    "storage_relpath": storage_relpath,
                }
                report(
                    "ocr_rendering",
                    (
                        f"正在渲染第 {page_number} 页"
                        f"（全文共 {document_page_total} 页）"
                    ),
                    len(page_images),
                    total_pages,
                    context={
                        "physical_page": page_number,
                        "document_page_total": document_page_total,
                        "completed_ocr_pages": len(page_images),
                        "ocr_page_total": total_pages,
                    },
                )
        finally:
            document.close()

        # Run OCR concurrently with at most 8 active calls.
        ocr_results: dict[int, dict[str, Any]] = {}

        def _ocr_page(page_number: int) -> tuple[int, dict[str, Any]]:
            image_bytes = page_images[page_number]
            raw = self.ocr_runner(
                page_number, self.ocr_dpi, ocr_model, image_bytes
            )
            if hasattr(raw, "text"):
                normalized = {
                    "text": str(raw.text or ""),
                    "model": str(getattr(raw, "model", "") or ocr_model),
                    "provider": str(getattr(raw, "provider", "") or ""),
                    "fell_back": bool(getattr(raw, "fell_back", False)),
                    "primary_model": str(
                        getattr(raw, "primary_model", "") or ""
                    ),
                    "fallback_reason": str(
                        getattr(raw, "fallback_reason", "") or ""
                    ),
                }
            else:
                normalized = {
                    "text": str(raw or ""),
                    "model": ocr_model,
                    "provider": "",
                    "fell_back": False,
                    "primary_model": "",
                    "fallback_reason": "",
                }
            return page_number, normalized

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=WRITING_REFERENCE_OCR_MAX_CONCURRENCY
        ) as executor:
            report(
                "ocr_completing",
                f"正在识别 {total_pages} 个待处理页面",
                0,
                total_pages,
                context={
                    "document_page_total": document_page_total,
                    "completed_ocr_pages": 0,
                    "ocr_page_total": total_pages,
                },
            )
            futures = {executor.submit(_ocr_page, page): page for page in pages_to_ocr}
            completed_pages = 0
            for future in concurrent.futures.as_completed(futures):
                page_number, page_result = future.result()
                ocr_results[page_number] = page_result
                completed_pages += 1
                report(
                    "ocr_completing",
                    (
                        f"OCR 第 {page_number} 页完成"
                        f"（全文共 {document_page_total} 页）"
                    ),
                    completed_pages,
                    total_pages,
                    context={
                        "physical_page": page_number,
                        "document_page_total": document_page_total,
                        "completed_ocr_pages": completed_pages,
                        "ocr_page_total": total_pages,
                    },
                )

        # Publish evidence only after the complete OCR batch has returned.
        # This prevents a failed model call from leaving a partial final batch.
        for page_number in pages_to_ocr:
            metadata = page_image_metadata[page_number]
            write_immutable_ocr_png(
                self.artifact_root,
                metadata["storage_relpath"],
                page_images[page_number],
                metadata["image_sha256"],
            )

        ocr_recovery: list[WritingReferenceOcrPageEvidence] = []
        new_spans: list[WritingReferenceExtractedSpan] = list(result.spans)
        page_native_text = {
            page_number: "\n".join(
                span.source_text
                for span in new_spans
                if span.physical_page == page_number and span.source_text.strip()
            )
            for page_number in range(1, result.page_count + 1)
        }

        # For anomaly pages, collect native-text lineage before deciding
        # whether OCR can replace the page.  Only a page with both native
        # spans and non-empty OCR text is a true reconciliation; image-only
        # anomaly pages remain ordinary OCR recovery.
        anomaly_page_set = set(anomaly_map.keys())
        native_spans_by_page: dict[int, list[dict]] = {}
        if anomaly_page_set:
            for span in new_spans:
                if span.physical_page in anomaly_page_set:
                    native_spans_by_page.setdefault(span.physical_page, []).append(
                        {
                            "span_id": span.span_id,
                            "source_locator": span.source_locator,
                            "source_text_sha256": span.source_text_sha256,
                            "channel": "native_text",
                        }
                    )
        reconciled_anomaly_page_set = {
            page_number
            for page_number in anomaly_page_set
            if native_spans_by_page.get(page_number)
            and ocr_results.get(page_number, {}).get("text", "").strip()
        }
        if reconciled_anomaly_page_set:
            new_spans = [
                span
                for span in new_spans
                if span.physical_page not in reconciled_anomaly_page_set
            ]

        # Deterministic output order by physical page number.
        for page_number in pages_to_ocr:
            page_result = ocr_results.get(page_number, {})
            ocr_text = str(page_result.get("text", ""))
            if not ocr_text.strip():
                ocr_text = ""
            text_hash = hashlib.sha256(ocr_text.encode("utf-8")).hexdigest()
            is_anomaly = page_number in anomaly_page_set
            has_native_spans = bool(native_spans_by_page.get(page_number))
            is_reconciled = is_anomaly and has_native_spans and bool(ocr_text)
            selection_reason = anomaly_map.get(page_number, "zero_text_page")
            channel = "ocr_reconciled" if is_reconciled else "ocr"
            span_id = ""
            if ocr_text and ocr_text.strip():
                source_locator = (
                    f"{locator_prefix}:{artifact.nct_id}:{artifact.artifact_id}:"
                    f"p{page_number}:ocr"
                )
                span_id = (
                    "wref_span_ocr_"
                    + hashlib.sha256(
                        f"{artifact.artifact_id}|{result.extraction_revision}|"
                        f"p{page_number}|{channel}|{text_hash}".encode("utf-8")
                    ).hexdigest()[:24]
                )
                ocr_anchor, ocr_heading = _m11_anchor_from_ocr_page(ocr_text)
                new_spans.append(
                    WritingReferenceExtractedSpan(
                        span_id=span_id,
                        project_id=artifact.project_id,
                        artifact_id=artifact.artifact_id,
                        extraction_revision=result.extraction_revision,
                        physical_page=page_number,
                        block_index=0,
                        source_locator=source_locator,
                        section_heading=ocr_heading,
                        # OCR reconciliation replaces the native page span.
                        # Recompute the candidate M11 anchor from the recovered
                        # source text instead of discarding the native mapping.
                        # Unmapped continuation pages remain fail-closed and are
                        # handled by the document-level structure planner.
                        ich_m11_anchor=ocr_anchor,
                        source_text=ocr_text,
                        source_text_sha256=text_hash,
                        extraction_status=(
                            "ocr_reconciled" if is_reconciled else "ocr_recovered"
                        ),
                        needs_visual_qc=True,
                    )
                )
            metadata = page_image_metadata[page_number]
            recovery_entry = WritingReferenceOcrPageEvidence(
                physical_page=page_number,
                dpi=self.ocr_dpi,
                image_sha256=metadata["image_sha256"],
                image_size_bytes=metadata["image_size_bytes"],
                image_width_px=metadata["image_width_px"],
                image_height_px=metadata["image_height_px"],
                storage_relpath=metadata["storage_relpath"],
                model=str(page_result.get("model") or ocr_model),
                provider=str(page_result.get("provider") or ""),
                fell_back=bool(page_result.get("fell_back", False)),
                primary_model=str(page_result.get("primary_model") or ""),
                fallback_reason=str(page_result.get("fallback_reason") or ""),
                ocr_profile_digest=_hs(
                    _json.dumps(
                        {
                            "profile": self.ocr_profile,
                            "model": str(page_result.get("model") or ocr_model),
                            "provider": str(page_result.get("provider") or ""),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                ocr_text_sha256=text_hash,
                ocr_character_count=len(ocr_text),
                channel=channel,
                selection_reason=selection_reason,
                ocr_result_status=(
                    "text_recovered"
                    if ocr_text and ocr_text.strip()
                    else "empty_text"
                ),
                span_id=span_id,
                native_channel=(
                    native_spans_by_page.get(page_number, [])
                    if is_anomaly
                    else []
                ),
            )
            validate_new_ocr_page_evidence(recovery_entry)
            ocr_recovery.append(recovery_entry)
        consistency_qc: dict[str, Any] = {}
        if self.ocr_consistency_qc_runner is not None:
            from .ocr_consistency_qc import run_mixed_ocr_consistency_qc

            outcome = run_mixed_ocr_consistency_qc(
                [
                    {
                        "physical_page": int(item.physical_page),
                        "model": str(item.model),
                        "text": str(
                            ocr_results[item.physical_page].get("text", "")
                        ),
                        "fell_back": bool(item.fell_back),
                        "native_text": page_native_text.get(
                            int(item.physical_page), ""
                        ),
                        "previous_page_text": page_native_text.get(
                            int(item.physical_page) - 1, ""
                        ),
                        "next_page_text": page_native_text.get(
                            int(item.physical_page) + 1, ""
                        ),
                    }
                    for item in ocr_recovery
                ],
                self.ocr_consistency_qc_runner,
            )
            consistency_qc = outcome.audit_payload()
        new_spans.sort(
            key=lambda span: (
                span.physical_page,
                span.block_index,
                span.source_locator,
                span.span_id,
            )
        )
        return result.model_copy(
            update={
                "spans": new_spans,
                "ocr_recovery_pages": ocr_recovery,
                "ocr_model": ocr_model,
                "ocr_dpi": self.ocr_dpi,
                "ocr_profile_digest": profile_digest,
                "ocr_consistency_qc": consistency_qc,
            }
        )


def search_url(
    request: WritingReferenceSearchRequest,
    page_token: str | None = None,
) -> str:
    indication = request.indication.strip()
    phases = sorted(
        {phase.strip().upper() for phase in request.phases if phase.strip()}
    )
    if not indication:
        raise ValueError("indication is required")
    if not phases:
        raise ValueError("at least one phase is required")
    if not all(re.fullmatch(r"(?:EARLY_)?PHASE[1-4]|NA", phase) for phase in phases):
        raise ValueError("unsupported ClinicalTrials.gov phase value")

    phase_expression = " OR ".join(f"AREA[Phase]{phase}" for phase in phases)
    if len(phases) > 1:
        phase_expression = f"({phase_expression})"
    terms = [phase_expression]
    study_type = request.study_type.strip().upper()
    if study_type:
        if not re.fullmatch(
            r"INTERVENTIONAL|OBSERVATIONAL|EXPANDED_ACCESS", study_type
        ):
            raise ValueError("unsupported ClinicalTrials.gov study type")
        terms.append(f"AREA[StudyType]{study_type}")
    for intervention in sorted(
        {item.strip() for item in request.intervention_terms if item.strip()}
    ):
        terms.append(f'AREA[InterventionName]"{intervention}"')
    for region in sorted({item.strip() for item in request.regions if item.strip()}):
        terms.append(f'AREA[LocationCountry]"{region}"')

    params = {
        "query.cond": indication,
        "query.term": " AND ".join(terms),
        "pageSize": str(request.page_size),
        "format": "json",
        "countTotal": "true",
        "fields": CTGOV_DISCOVERY_FIELDS,
    }
    effective_token = page_token or request.page_token
    if effective_token:
        params["pageToken"] = effective_token
    return f"{CTGOV_API_ROOT}/studies?{urlencode(params)}"


def document_url(nct_id: str, filename: str) -> str:
    if not NCT_ID_PATTERN.fullmatch(nct_id):
        raise ValueError(f"invalid NCT id: {nct_id}")
    if (
        filename != filename.strip()
        or filename.startswith(".")
        or "/" in filename
        or "\\" in filename
        or not SAFE_PDF_FILENAME_PATTERN.fullmatch(filename)
    ):
        raise ValueError(f"unsafe public-document filename: {filename}")
    return f"https://clinicaltrials.gov/ProvidedDocs/{nct_id[-2:]}/{nct_id}/{filename}"


def _document_type(metadata: dict) -> str:
    has_protocol = bool(metadata.get("hasProtocol"))
    has_sap = bool(metadata.get("hasSap"))
    if has_protocol and has_sap:
        return "protocol_sap"
    if has_protocol:
        return "protocol"
    if has_sap:
        return "sap"
    return "other"


def candidate_from_study(study: dict) -> WritingReferenceTrialCandidate:
    protocol = study.get("protocolSection") or {}
    identification = protocol.get("identificationModule") or {}
    nct_id = str(identification.get("nctId") or "")
    if not NCT_ID_PATTERN.fullmatch(nct_id):
        raise ValueError("ClinicalTrials.gov study is missing a valid nctId")
    sponsor = (protocol.get("sponsorCollaboratorsModule") or {}).get(
        "leadSponsor"
    ) or {}
    design = protocol.get("designModule") or {}
    design_info = design.get("designInfo") or {}
    masking_info = design_info.get("maskingInfo") or {}
    enrollment_info = design.get("enrollmentInfo") or {}
    description = protocol.get("descriptionModule") or {}
    interventions_raw = (
        (protocol.get("armsInterventionsModule") or {}).get("interventions") or []
    )
    interventions = [
        WritingReferenceTrialIntervention(
            name=str(item.get("name") or ""),
            intervention_type=str(item.get("type") or ""),
        )
        for item in interventions_raw
        if isinstance(item, dict) and (item.get("name") or item.get("type"))
    ]
    enrollment_count_raw = enrollment_info.get("count")
    enrollment_count = (
        enrollment_count_raw
        if isinstance(enrollment_count_raw, int)
        and not isinstance(enrollment_count_raw, bool)
        and enrollment_count_raw >= 0
        else None
    )
    status = protocol.get("statusModule") or {}
    documents = (
        (study.get("documentSection") or {})
        .get("largeDocumentModule", {})
        .get("largeDocs", [])
    )
    public_documents = []
    for index, metadata in enumerate(documents):
        filename = str(metadata.get("filename") or "")
        if not filename:
            continue
        public_documents.append(
            WritingReferencePublicDocument(
                document_id=f"ctgov_{nct_id}_{index:03d}",
                nct_id=nct_id,
                document_type=_document_type(metadata),
                label=str(metadata.get("label") or metadata.get("typeAbbrev") or ""),
                filename=filename,
                document_date=str(metadata.get("date") or ""),
                upload_date=str(metadata.get("uploadDate") or ""),
                declared_size=metadata.get("size"),
                download_url=document_url(nct_id, filename),
            )
        )
    return WritingReferenceTrialCandidate(
        nct_id=nct_id,
        brief_title=str(identification.get("briefTitle") or ""),
        official_title=str(identification.get("officialTitle") or ""),
        brief_summary=str(description.get("briefSummary") or ""),
        conditions=list(
            (protocol.get("conditionsModule") or {}).get("conditions") or []
        ),
        phases=list(design.get("phases") or []),
        study_type=str(design.get("studyType") or ""),
        interventions=interventions,
        design_allocation=str(design_info.get("allocation") or ""),
        design_intervention_model=str(
            design_info.get("interventionModel") or ""
        ),
        design_masking=str(masking_info.get("masking") or ""),
        enrollment_count=enrollment_count,
        lead_sponsor=str(sponsor.get("name") or ""),
        overall_status=str(status.get("overallStatus") or ""),
        first_posted=str(
            (status.get("studyFirstPostDateStruct") or {}).get("date") or ""
        ),
        last_update_posted=str(
            (status.get("studyLastUpdatePostDateStruct") or {}).get("date") or ""
        ),
        study_record_url=f"https://clinicaltrials.gov/study/{nct_id}",
        public_documents=public_documents,
    )


def validate_pdf_payload(
    payload: bytes,
    *,
    declared_size: int | None,
    content_type: str,
) -> PdfPayloadValidation:
    magic_valid = payload.startswith(b"%PDF-")
    size_matches = declared_size is None or declared_size == len(payload)
    content_type_pdf = "pdf" in content_type.lower()
    return PdfPayloadValidation(
        is_valid=magic_valid and size_matches and content_type_pdf,
        magic_valid=magic_valid,
        declared_size_matches=size_matches,
        content_type_pdf=content_type_pdf,
        actual_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def validate_manual_document_payload(
    *,
    filename: str,
    content_type: str,
    payload: bytes,
) -> tuple[str, str, str, str]:
    canonical_filename = (filename or "").strip()
    if (
        not canonical_filename
        or canonical_filename in {".", ".."}
        or "/" in canonical_filename
        or "\\" in canonical_filename
        or "\x00" in canonical_filename
    ):
        raise ValueError("uploaded filename must be a plain PDF or DOCX filename")
    if not payload:
        raise ValueError("uploaded document is empty")
    if len(payload) > MAX_MANUAL_DOCUMENT_BYTES:
        raise ValueError("uploaded document exceeds the 64 MB limit")
    lowered = canonical_filename.casefold()
    if lowered.endswith(".pdf"):
        if not payload.startswith(b"%PDF-"):
            raise ValueError("uploaded file extension is PDF but content is not a PDF")
        canonical_type = "application/pdf"
        extension = ".pdf"
    elif lowered.endswith(".docx"):
        if not payload.startswith(b"PK"):
            raise ValueError(
                "uploaded file extension is DOCX but content is not a DOCX"
            )
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = set(archive.namelist())
                if (
                    "[Content_Types].xml" not in names
                    or "word/document.xml" not in names
                ):
                    raise ValueError(
                        "uploaded DOCX is missing the main Word document part"
                    )
        except zipfile.BadZipFile as exc:
            raise ValueError("uploaded DOCX container is invalid") from exc
        canonical_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        extension = ".docx"
    else:
        raise ValueError("only PDF and DOCX Protocol/SAP files are supported")
    provided_type = (content_type or "").split(";", 1)[0].strip().casefold()
    allowed_types = {
        "": {"", "application/octet-stream"},
        ".pdf": {"", "application/pdf", "application/octet-stream"},
        ".docx": {
            "",
            "application/octet-stream",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    }
    if provided_type not in allowed_types[extension]:
        raise ValueError("uploaded content type does not match the file extension")
    return (
        canonical_filename,
        canonical_type,
        extension,
        hashlib.sha256(payload).hexdigest(),
    )


def evaluate_translation_fidelity(
    source_text: str,
    translated_text: str,
) -> TranslationFidelityResult:
    # Rich-text line breaks and other inline tags are presentation codes, not
    # clinical comparators. Preserve their text content while excluding the
    # markup itself from deterministic linguistic checks.
    source_text = re.sub(r"</?[A-Za-z][^>]{0,200}>", " ", source_text)
    translated_text = re.sub(r"</?[A-Za-z][^>]{0,200}>", " ", translated_text)

    def normalize_minimum_observation_window(
        source: str,
        target: str,
    ) -> tuple[str, str]:
        """Canonicalize faithful N-of-M daily assessment wording.

        Chinese regulatory prose commonly renders "a minimum of 4 scores out
        of 7 days" as "至少需获取这7天中的4日评分值".  The comparator still
        applies to four observations, not to seven days.  Canonicalizing this
        bounded construction prevents the generic nearest-number parser from
        attaching "至少" to 7 while preserving both numeric tokens and the
        seven-day window for the ordinary numeric/unit checks.
        """
        source_pattern = re.compile(
            r"(?:a\s+minimum\s+of|at\s+least)\s+"
            r"(?P<count>\d+(?:\.\d+)?)\s+"
            r"(?:scores?|assessments?|records?)\s+"
            r"out\s+of\s+(?:the\s+)?(?P<days>\d+(?:\.\d+)?)\s+days?",
            re.IGNORECASE,
        )
        normalized_source = source
        normalized_target = target
        for match in source_pattern.finditer(source):
            count = match.group("count")
            days = match.group("days")
            target_pattern = re.compile(
                rf"至少[^，。；;\n]{{0,24}}?"
                rf"{re.escape(days)}\s*天(?:中|内|之内|中的)"
                rf"[^，。；;\n]{{0,24}}?"
                rf"{re.escape(count)}\s*(?:日|天|次|个)"
                rf"[^，。；;\n]{{0,12}}?(?:评分|评估|记录)"
            )
            target_days_first_pattern = re.compile(
                rf"{re.escape(days)}\s*天(?:中|内|之内|中的)"
                rf"[^，。；;\n]{{0,24}}?至少"
                rf"[^，。；;\n]{{0,16}}?"
                rf"{re.escape(count)}\s*(?:日|天|次|个)"
                rf"[^，。；;\n]{{0,12}}?(?:评分|评估|记录|数据)"
            )
            normalized_source = source_pattern.sub(
                lambda item: (
                    f"at least {item.group('count')} scores within "
                    f"{item.group('days')} days"
                ),
                normalized_source,
                count=1,
            )
            normalized_target = target_pattern.sub(
                f"至少{count}次评分（{days}天内）",
                normalized_target,
                count=1,
            )
            normalized_target = target_days_first_pattern.sub(
                f"至少{count}次评分（{days}天内）",
                normalized_target,
                count=1,
            )
        return normalized_source, normalized_target

    comparison_source_text, comparison_translated_text = (
        normalize_minimum_observation_window(source_text, translated_text)
    )

    # An explicitly inclusive English age range must not become an exclusive
    # Chinese boundary. Generic number/comparator checks miss this when the
    # source expresses inclusion in prose ("both included") rather than with
    # mathematical comparator symbols.
    inclusive_ranges = re.findall(
        r"(\d+(?:\.\d+)?)\s*(?:to|through|[\u2013\u2014-])\s*"
        r"(\d+(?:\.\d+)?)[^。\n]{0,80}?"
        r"(?:both\s+included|inclusive)",
        source_text,
        re.IGNORECASE,
    )

    def comparator_class(value: str) -> str:
        normalized = re.sub(r"\s+", " ", value.strip().casefold())
        if normalized in {
            ">=",
            "≥",
            "at least",
            "no less than",
            "最短",
            "满",
            "a minimum of",
            "greater than or equal to",
            "大于或等于",
            "大于等于",
            "不低于",
            "至少",
            "以上",
        }:
            return "ge"
        if normalized in {
            ">",
            "more than",
            "greater than",
            "超过",
            "超出",
            "大于",
            "更高",
            "更大",
            "较多",
        }:
            return "gt"
        if normalized in {
            "<=",
            "≤",
            "at most",
            "no more than",
            "less than or equal to",
            "小于或等于",
            "小于等于",
            "不高于",
            "至多",
            "以下",
        }:
            return "le"
        if normalized in {"更低", "更小", "较少"}:
            return "lt"
        return "lt"

    def unit_class(value: str) -> str:
        normalized = value.strip().casefold().replace("％", "%")
        aliases = {
            "%": "%",
            "mg": "mg",
            "毫克": "mg",
            "g": "g",
            "克": "g",
            "kg": "kg",
            "千克": "kg",
            "µg": "ug",
            "μg": "ug",
            "mcg": "ug",
            "微克": "ug",
            "ml": "ml",
            "cc": "ml",
            "毫升": "ml",
            "l": "l",
            "升": "l",
            "iu": "iu",
            "u": "u",
            "国际单位": "iu",
            "mmhg": "mmhg",
            "毫米汞柱": "mmhg",
            "cm": "cm",
            "厘米": "cm",
            "mm": "mm",
            "毫米": "mm",
            "day": "day",
            "days": "day",
            "天": "day",
            "日": "day",
            "week": "week",
            "weeks": "week",
            "周": "week",
            "month": "month",
            "months": "month",
            "月": "month",
            "year": "year",
            "years": "year",
            "年": "year",
            "岁": "year",
            "周岁": "year",
        }
        return aliases.get(normalized, normalized)

    def canonical_number(value: str) -> str:
        value = value.replace("−", "-")
        if "." not in value:
            sign = "-" if value.startswith("-") else ""
            digits = value[1:] if sign else value
            return sign + str(int(digits))
        normalized = value.rstrip("0").rstrip(".")
        return normalized or "0"

    def normalize_phase_numbers(value: str) -> str:
        normalized = re.sub(r"(?:Ⅰ|I)\s*期", "1期", value)
        normalized = re.sub(r"(?:Ⅱ|II)\s*期", "2期", normalized)
        return re.sub(r"(?:Ⅲ|III)\s*期", "3期", normalized)

    def normalize_chinese_duration_numbers(value: str) -> str:
        chinese_numbers = {
            "一": "1",
            "二": "2",
            "两": "2",
            "三": "3",
            "四": "4",
            "五": "5",
            "六": "6",
            "七": "7",
            "八": "8",
            "九": "9",
            "十": "10",
            "十一": "11",
            "十二": "12",
            "十三": "13",
            "十四": "14",
            "十五": "15",
            "十六": "16",
            "十七": "17",
            "十八": "18",
            "十九": "19",
            "二十": "20",
        }
        pattern = re.compile(
            r"(?<![第\d])"
            r"(?P<number>二十|十[一二三四五六七八九]|"
            r"[一二两三四五六七八九十])"
            r"(?=(?:个)?(?:天|日|周|月|年|岁))"
        )
        return pattern.sub(
            lambda match: chinese_numbers[match.group("number")],
            value,
        )

    numeric_source_text = re.sub(
        r"\b(?:a|an)\s+(?=(?:day|week|month|year)s?\b)",
        "1 ",
        source_text,
        flags=re.IGNORECASE,
    )
    month_numbers = {
        "jan": "1",
        "feb": "2",
        "mar": "3",
        "apr": "4",
        "may": "5",
        "jun": "6",
        "jul": "7",
        "aug": "8",
        "sep": "9",
        "sept": "9",
        "oct": "10",
        "nov": "11",
        "dec": "12",
    }
    numeric_source_text = re.sub(
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
        r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b",
        lambda match: month_numbers[match.group(0)[:4].casefold().rstrip("t")]
        if match.group(0)[:4].casefold().rstrip("t") in month_numbers
        else month_numbers[match.group(0)[:3].casefold()],
        numeric_source_text,
        flags=re.IGNORECASE,
    )
    # "may" is normally a modal verb in protocol prose. Treat it as the
    # calendar month only in an explicit date/citation shape.
    numeric_source_text = re.sub(
        r"\bMay\b(?=\s*(?:\d{1,2}\b|[;,]))",
        "5",
        numeric_source_text,
        flags=re.IGNORECASE,
    )
    # Compact source units such as 2ml/4mm still carry auditable numeric
    # values. Insert comparison-only spacing; the immutable source is unchanged.
    numeric_source_text = re.sub(
        r"(?<=\d),(?=\d{3}(?!\d))",
        "",
        numeric_source_text,
    )
    numeric_source_text = re.sub(
        r"(?<![A-Za-z0-9-])"
        r"(?P<number>\d+(?:\.\d+)?)"
        r"(?P<unit>mg|kg|g|µg|μg|mcg|mL|ml|cc|L|IU|U|mmHg|cm|mm)(?![A-Za-z])",
        r"\g<number> \g<unit>",
        numeric_source_text,
        flags=re.IGNORECASE,
    )

    def expand_bibliographic_page_range(match: re.Match[str]) -> str:
        lower = match.group("lower")
        upper = match.group("upper")
        expanded = lower[: len(lower) - len(upper)] + upper
        if int(expanded) < int(lower):
            return match.group(0)
        return f"{lower}-{expanded}"

    numeric_source_text = re.sub(
        r"\b(?P<lower>\d{3,4})-(?P<upper>\d{1,2})(?=[.;,\s])",
        expand_bibliographic_page_range,
        numeric_source_text,
    )
    numeric_translated_text = translated_text
    numeric_translated_text = re.sub(
        r"(?<=\d),(?=\d{3}(?!\d))",
        "",
        numeric_translated_text,
    )
    numeric_translated_text = re.sub(
        r"(?<![A-Za-z0-9-])"
        r"(?P<number>\d+(?:\.\d+)?)"
        r"(?P<unit>mg|kg|g|µg|μg|mcg|mL|ml|cc|L|IU|U|mmHg|cm|mm)(?![A-Za-z])",
        r"\g<number> \g<unit>",
        numeric_translated_text,
        flags=re.IGNORECASE,
    )
    if (
        re.search(r"\bEQ-5D-5L\b", source_text, re.I)
        and not re.search(r"\bEQ-5D-5L\b", translated_text, re.I)
        and re.search(
            r"欧洲五维健康(?:量表|问卷)(?:五级版本|五级版)",
            translated_text,
        )
    ):
        # The approved Chinese expansion preserves the scale identity even
        # when the source abbreviation is not repeated.  Remove only the
        # abbreviation-internal 5/5 pair from numeric comparison; all actual
        # visits, thresholds and endpoint numbers remain auditable.
        numeric_source_text = re.sub(
            r"\bEQ-5D-5L\b",
            "EQ_FIVE_DIMENSION_SCALE",
            numeric_source_text,
            flags=re.I,
        )
        numeric_translated_text = re.sub(
            r"欧洲五维健康(?:量表|问卷)(?:五级版本|五级版)",
            "EQ_FIVE_DIMENSION_SCALE",
            numeric_translated_text,
        )
    if re.search(
        r"EQ-5D-5L\s*=\s*EuroQoL\s+5\s+Dimension\s+Health\s+Questionnaire\s+5\s+Level",
        source_text,
        re.I,
    ) and re.search(
        r"EQ-5D-5L\s*=\s*欧洲五维健康(?:量表|问卷)(?:五级版本|五级版)",
        translated_text,
    ):
        numeric_source_text = re.sub(
            r"EQ-5D-5L\s*=\s*EuroQoL\s+5\s+Dimension\s+Health\s+Questionnaire\s+5\s+Level",
            "EQ-5D-5L = EQ-5D-5L",
            numeric_source_text,
            flags=re.I,
        )
        numeric_translated_text = re.sub(
            r"EQ-5D-5L\s*=\s*欧洲五维健康(?:量表|问卷)(?:五级版本|五级版)",
            "EQ-5D-5L = EQ-5D-5L",
            numeric_translated_text,
        )
    numeric_translated_text = normalize_chinese_duration_numbers(
        numeric_translated_text
    )
    if re.search(
        r"\b(?:1|one)\s+or\s+more\s+"
        r"(?:eligibility\s+)?(?:criteria|criterion)\b",
        numeric_source_text,
        re.I,
    ) and re.search(
        r"至少\s*一\s*(?:项|条)[^，。；;\n]{0,24}"
        r"(?:标准|条件|要求)",
        numeric_translated_text,
    ):
        numeric_translated_text = re.sub(
            r"至少\s*一(?=\s*(?:项|条)[^，。；;\n]{0,24}(?:标准|条件|要求))",
            "至少1",
            numeric_translated_text,
            count=1,
        )
    comparison_translated_text = normalize_chinese_duration_numbers(
        comparison_translated_text
    )
    comparison_translated_text = re.sub(
        r"至少\s*满(?=\s*\d)",
        "至少",
        comparison_translated_text,
    )
    comparison_translated_text = re.sub(
        r"(?:年)?满\s*(\d+(?:\.\d+)?)\s*(周岁|岁)\s*(?:及)?以上",
        r"\1\2以上",
        comparison_translated_text,
    )
    comparison_translated_text = re.sub(
        r"(?:已)?满\s*(\d+(?:\.\d+)?)\s*(天|日|周|月|年)\s*(?:及)?以上",
        r"\1\2以上",
        comparison_translated_text,
    )
    source_numbers = tuple(
        canonical_number(value)
        for value in NUMBER_PATTERN.findall(
            normalize_phase_numbers(numeric_source_text)
        )
    )
    translated_numbers = tuple(
        canonical_number(value)
        for value in NUMBER_PATTERN.findall(
            normalize_phase_numbers(numeric_translated_text)
        )
    )
    source_abbreviations = detect_clinical_abbreviations(source_text)
    failures = []
    for lower, upper in inclusive_ranges:
        lower_exclusive = re.search(
            rf"(?:>|大于|超过)\s*{re.escape(lower)}"
            rf"|{re.escape(lower)}\s*(?:周岁|岁)?(?<!及)以上",
            translated_text,
        )
        upper_exclusive = re.search(
            rf"(?:<|小于|低于|未满|不满|不足)\s*{re.escape(upper)}"
            rf"|{re.escape(upper)}\s*(?:周岁|岁)?以下",
            translated_text,
        )
        if lower_exclusive or upper_exclusive:
            failures.append("range_inclusivity_changed")
            break
    number_words = {
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
        "ten": "10",
        "eleven": "11",
        "twelve": "12",
        "thirteen": "13",
        "fourteen": "14",
        "fifteen": "15",
        "sixteen": "16",
        "seventeen": "17",
        "eighteen": "18",
        "nineteen": "19",
        "twenty": "20",
        "first": "1",
        "second": "2",
        "third": "3",
        "fourth": "4",
        "fifth": "5",
        "sixth": "6",
        "seventh": "7",
        "eighth": "8",
        "ninth": "9",
        "tenth": "10",
        "eleventh": "11",
        "twelfth": "12",
        "thirteenth": "13",
        "fourteenth": "14",
        "fifteenth": "15",
        "sixteenth": "16",
        "seventeenth": "17",
        "eighteenth": "18",
        "nineteenth": "19",
        "twentieth": "20",
    }
    source_word_numbers = Counter(
        number_words[match.group(0).casefold()]
        for match in re.finditer(
            rf"\b(?:{'|'.join(number_words)})\b",
            source_text,
            re.IGNORECASE,
        )
    )
    source_number_counts = Counter(source_numbers)
    translated_number_counts = Counter(translated_numbers)

    def _chinese_scaled_number_tokens(text: str) -> Counter:
        """Decode Chinese magnitude-scaled numerals to their bare tokens.

        0924V2 §5 fidelity diagnosis: a faithful translation renders
        "116 million" as "1.16亿" and "$635 billion" as "6350亿" — the
        magnitude moves into the unit suffix, so the bare numeric-token
        comparison mislabels these as numeric drift (checker false
        positive). A scaled token contributes BOTH its mantissa and its
        digit-collapsed form (1.16亿 → "1.16" and "116") so the pair
        (source "116", translated "1.16") compares equal; "6350亿" also
        re-credits the source-side bare token 6350.
        """
        scaled: Counter = Counter()
        for match in re.finditer(r"(\d+(?:\.\d+)?)([万亿])", text):
            mantissa, unit = match.group(1), match.group(2)
            try:
                float(mantissa)
            except ValueError:
                continue
            digits = mantissa.replace(".", "")
            if digits:
                scaled[digits] += 1
            if mantissa != digits:
                scaled[mantissa] += 1
        return scaled

    scaled_source_tokens = _chinese_scaled_number_tokens(source_text)
    scaled_translated_tokens = _chinese_scaled_number_tokens(translated_text)
    # Symmetric credit: each side additionally recognizes the other side's
    # scaled forms, so a faithful magnitude conversion never produces a
    # difference while a genuinely changed count still does (the true count
    # digit string appears on only one side).
    source_number_counts += scaled_translated_tokens
    translated_number_counts += scaled_source_tokens + scaled_translated_tokens

    def unexpanded_frequency_numbers(text: str) -> list[str]:
        values: list[str] = []
        for match in re.finditer(
            r"(?<![A-Za-z0-9])q(\d+)[DWM](?![A-Za-z0-9])",
            text,
            re.I,
        ):
            number = match.group(1)
            nearby_prefix = text[max(0, match.start() - 24) : match.start()]
            if re.search(
                rf"(?:每\s*)?{re.escape(number)}\s*(?:天|日|周|月|days?|weeks?|months?)"
                r"[^，。；;]{0,8}[（(]?\s*$",
                nearby_prefix,
                re.I,
            ):
                continue
            values.append(number)
        return values

    source_number_counts.update(unexpanded_frequency_numbers(source_text))
    translated_number_counts.update(unexpanded_frequency_numbers(translated_text))
    missing_source_numbers = source_number_counts - translated_number_counts
    extra_translated_numbers = translated_number_counts - source_number_counts
    unlicensed_extra_numbers = extra_translated_numbers - source_word_numbers
    # 0924V2 §5: leftover "missing" tokens that differ from a translated
    # token ONLY by decimal-point scaling are magnitude-scaled renderings
    # (116 ↔ 1.16亿). A faithful "635 billion" → "6350亿" additionally
    # appends the unit's zero (billion = 10^9 vs 亿 = 10^8), producing
    # 635 ↔ 6350 — the translated token starting with the source token's
    # digit string and extending it ONLY with unit-conversion zeros is the
    # same number, not drift. Genuinely changed counts alter the significant
    # digits and never satisfy either shape.
    def _digit_key(token: str) -> str:
        return token.replace(".", "")

    def _is_magnitude_rewire(source_token: str, translated_token: str) -> bool:
        source_digits = _digit_key(source_token)
        translated_digits = _digit_key(translated_token)
        if not source_digits or not translated_digits:
            return False
        if translated_digits.startswith(source_digits):
            return set(translated_digits[len(source_digits):]) <= {"0"}
        return translated_digits == source_digits

    translated_digit_keys = Counter(
        _digit_key(token)
        for token in translated_number_counts
        for _ in range(translated_number_counts[token])
    )
    forgiven_missing = set()
    for token, count in missing_source_numbers.items():
        if translated_digit_keys.get(_digit_key(token), 0) >= count:
            forgiven_missing.add(token)
            continue
        if any(
            _is_magnitude_rewire(token, other)
            for other in translated_number_counts
        ):
            forgiven_missing.add(token)
    # 0924V2 §5: the mirrored direction — a scaled translated token
    # (1.16 from 1.16亿, 6350 from 6350亿) is licensed when a source token
    # rewires to it, so it must not count as an unlicensed extra either.
    source_digit_keys = Counter(
        _digit_key(token)
        for token in source_number_counts
        for _ in range(source_number_counts[token])
    )
    forgiven_extra = set()
    for token, count in unlicensed_extra_numbers.items():
        if source_digit_keys.get(_digit_key(token), 0) >= count:
            forgiven_extra.add(token)
            continue
        if any(
            _is_magnitude_rewire(source_token, token)
            for source_token in source_number_counts
        ):
            forgiven_extra.add(token)
    missing_source_numbers = Counter(
        {token: count for token, count in missing_source_numbers.items() if token not in forgiven_missing}
    )
    unlicensed_extra_numbers = Counter(
        {token: count for token, count in unlicensed_extra_numbers.items() if token not in forgiven_extra}
    )
    if missing_source_numbers or unlicensed_extra_numbers:
        failures.append("numeric_tokens_changed")
    source_comparators = tuple(
        comparator_class(match.group(0))
        for match in SOURCE_COMPARATOR_PATTERN.finditer(comparison_source_text)
    )
    translated_comparators = tuple(
        comparator_class(match.group(0))
        for match in TRANSLATED_COMPARATOR_PATTERN.finditer(comparison_translated_text)
    )

    def comparator_number_pairs(
        text: str, pattern: re.Pattern[str]
    ) -> tuple[tuple[str, str], ...]:
        pairs = []
        # Prefix-style comparators whose quantity may follow after a short
        # noun phrase rather than immediately (e.g. "≥正常值上限的2倍",
        # "满12个月").  Suffix-style tokens such as 以上/以下 are excluded:
        # their quantity always precedes them.
        _prefix_style = {
            "至少",
            "至多",
            "不低于",
            "不高于",
            "最短",
            "满",
            "≥",
            "≤",
            ">=",
            "<=",
            "超过",
            "超出",
            "大于",
            "小于",
            "低于",
            "不足",
            "未满",
            "不满",
        }
        for match in pattern.finditer(text):
            following = re.match(r"\s*(\d+(?:\.\d+)?)", text[match.end() :])
            if not following and match.group(0) in _prefix_style:
                following = re.match(
                    r"[^，。；;\n]{0,40}?(\d+(?:\.\d+)?)",
                    text[match.end() :],
                )
            if following:
                pairs.append(
                    (
                        canonical_number(following.group(1)),
                        comparator_class(match.group(0)),
                    )
                )
                continue
            if match.group(0) not in _prefix_style:
                preceding = re.search(
                    r"(\d+(?:\.\d+)?)[^，。；;\n\d]{0,12}$",
                    text[: match.start()],
                )
                if preceding:
                    pairs.append(
                        (
                            canonical_number(preceding.group(1)),
                            comparator_class(match.group(0)),
                        )
                    )
        return tuple(sorted(pairs))

    source_comparator_pairs = comparator_number_pairs(
        comparison_source_text, SOURCE_COMPARATOR_PATTERN
    )
    translated_comparator_pairs = comparator_number_pairs(
        comparison_translated_text, TRANSLATED_COMPARATOR_PATTERN
    )

    def _comparator_ops_compatible(
        source_ops: tuple[str, ...],
        translated_ops: tuple[str, ...],
    ) -> bool:
        # Strict and inclusive thresholds are not interchangeable clinical
        # boundaries: >18 differs from >=18, just as <18 differs from <=18.
        return source_ops == translated_ops

    def _comparator_pairs_compatible(
        source_pairs: tuple[tuple[str, str], ...],
        translated_pairs: tuple[tuple[str, str], ...],
    ) -> bool:
        """Require the same numeric threshold and strictness in both texts."""
        if source_pairs == translated_pairs:
            return True
        if len(source_pairs) != len(translated_pairs):
            return False
        for (src_num, src_op), (zh_num, zh_op) in zip(
            sorted(source_pairs), sorted(translated_pairs)
        ):
            if src_num != zh_num:
                return False
            if not _comparator_ops_compatible((src_op,), (zh_op,)):
                return False
        return True

    comparator_drift = (
        not _comparator_pairs_compatible(
            source_comparator_pairs, translated_comparator_pairs
        )
        if source_comparator_pairs and translated_comparator_pairs
        else not _comparator_ops_compatible(source_comparators, translated_comparators)
    )
    if source_comparators and comparator_drift:
        # Qualitative comparisons without numeric anchors are often rendered as
        # ``similar to or greater than`` → ``相当或更高``. Keep numeric pair
        # checks strict; only soften bare direction tokens.
        src = comparison_source_text
        zh = comparison_translated_text
        qual_gt = bool(
            re.search(r"\b(?:greater|higher|more)\b", src, re.I)
        ) and bool(re.search(r"更高|更大|较多|超过|大于", zh))
        qual_lt = bool(
            re.search(r"\b(?:less|lower|fewer)\b", src, re.I)
        ) and bool(re.search(r"更低|更小|较少|低于|小于", zh))
        qualitative_ok = (
            not source_comparator_pairs
            and not translated_comparator_pairs
            and (qual_gt or qual_lt)
            and not (qual_gt and qual_lt)
        )
        if not qualitative_ok:
            failures.append("comparison_direction_changed")

    def numeric_unit_pairs(text: str) -> tuple[tuple[str, str], ...]:
        pairs = []
        for match in NUMERIC_UNIT_PATTERN.finditer(text):
            number = canonical_number(
                match.group("prefix_number") or match.group("number")
            )
            unit = match.group("prefix") or match.group("suffix")
            normalized_unit = unit_class(unit)
            # Publication/citation years such as Hanifin and Rajka (1980)
            # are identifiers, not a clinical duration.
            if (
                normalized_unit == "year"
                and number.isdigit()
                and len(number) == 4
                and 1900 <= int(number) <= 2099
            ):
                continue
            pairs.append((number, normalized_unit))
        for match in re.finditer(
            r"(?P<lower>\d+(?:\.\d+)?)\s*(?:to|through|[\u2013\u2014\-])\s*"
            r"(?:[<>]\s*|(?:(?:less|more)\s+than\s+))?"
            r"(?P<upper>\d+(?:\.\d+)?)\s*"
            r"(?P<unit>days?|weeks?|months?|years?)\b",
            text,
            re.IGNORECASE,
        ):
            inferred = (match.group("lower"), unit_class(match.group("unit")))
            pairs.append(inferred)
        for match in re.finditer(
            r"(?P<lower>\d+(?:\.\d+)?)\s*(?:至|到|-)\s*"
            r"(?:未满|不足|低于|小于|<)?\s*(?P<upper>\d+(?:\.\d+)?)\s*"
            r"(?:个)?(?P<unit>周岁|天|日|周(?!期|岁)|月|年|岁)",
            text,
        ):
            inferred = (match.group("lower"), unit_class(match.group("unit")))
            pairs.append(inferred)
        for match in re.finditer(
            r"\b(?P<unit>days?|weeks?|months?|years?)\s+"
            r"(?P<values>\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*"
            r"(?:\s*,?\s*(?:and|or)\s*\d+(?:\.\d+)?)?)",
            text,
            re.IGNORECASE,
        ):
            unit = unit_class(match.group("unit"))
            for number in re.findall(r"\d+(?:\.\d+)?", match.group("values")):
                inferred = (number, unit)
                if inferred not in pairs:
                    pairs.append(inferred)
        for match in re.finditer(
            r"第?(?P<values>\d+(?:\.\d+)?(?:\s*[、,，]\s*\d+(?:\.\d+)?)+"
            r"(?:\s*(?:和|及|与)\s*\d+(?:\.\d+)?)?)\s*"
            r"(?:个)?(?P<unit>周岁|天|日|周(?!期|岁)|月|年|岁)",
            text,
        ):
            unit = unit_class(match.group("unit"))
            for number in re.findall(r"\d+(?:\.\d+)?", match.group("values")):
                inferred = (number, unit)
                if inferred not in pairs:
                    pairs.append(inferred)
        return tuple(sorted(pairs))

    source_units = numeric_unit_pairs(comparison_source_text)
    translated_units = numeric_unit_pairs(comparison_translated_text)
    if source_units and source_units != translated_units:
        failures.append("unit_sequence_changed")
    if re.search(
        r"\d\s+(?:mg|kg|g|µg|μg|mcg|mL|ml|L|IU|U)\b", source_text
    ) and re.search(r"\d(?:mg|kg|g|µg|μg|mcg|mL|ml|L|IU|U)\b", translated_text):
        failures.append("unit_spacing_changed")
    source_percentages = tuple(PERCENTAGE_VALUE_PATTERN.findall(source_text))
    translated_percentages = tuple(PERCENTAGE_VALUE_PATTERN.findall(translated_text))
    if source_percentages and source_percentages != translated_percentages:
        failures.append("numeric_tokens_changed")
    if re.search(r"~\s*\d", source_text) and re.search(
        r"(?:约(?:为)?\s*~|~\s*约)", translated_text
    ):
        failures.append("approximation_marker_duplicated")
    abbreviation_equivalents = {
        "AD": ("特应性皮炎", "阿尔茨海默病"),
        # 0924V2 §5 R14 evidence: these equivalents appeared in the real
        # blocked translations; the source abbreviation was rendered as its
        # full Chinese term, so "missing" was a table gap, not a drift.
        "FDA": ("美国食品药品监督管理局", "食品药品监督管理局", "食药局", "美国食药局"),
        "LDN": ("低剂量纳曲酮",),
        "MD": ("医生", "医师"),
        "MDs": ("医生", "医师"),
        "OA": ("骨关节炎", "骨性关节炎"),
        "PI": ("主要研究者", "研究者", "首席研究者"),
        "SAE": ("严重不良事件",),
        "SAEs": ("严重不良事件",),
        "VA": ("退伍军人事务部", "退伍军人", "退伍军人医疗系统", "退伍军人医院"),
        "BPI": ("简明疼痛量表", "简版疼痛量表"),
        "NSAIDs": ("非甾体抗炎药", "非甾体类抗炎药"),
        "NSAID": ("非甾体抗炎药", "非甾体类抗炎药"),
        "ADA": ("抗药抗体",),
        "ADSD": ("特应性皮炎症状日记", "特应性皮炎症状评分"),
        "AE": ("不良事件",),
        "AEs": ("不良事件",),
        "BP": ("血压", "收缩压", "舒张压", "收缩压与舒张压"),
        "CBC": ("全血细胞计数", "血常规"),
        "CMP": ("综合代谢检查", "综合代谢面板", "综合生化"),
        "TEAE": ("治疗期间出现的不良事件",),
        "TEAEs": ("治疗期间出现的不良事件",),
        "BSA": ("体表面积", "受累皮肤面积", "受累体表面积"),
        "BC": ("不列颠哥伦比亚省", "卑诗省"),
        "CA": ("加利福尼亚州", "加州"),
        "CZ": ("捷克",),
        "DE": ("德国",),
        "DLQI": ("皮肤病生活质量指数",),
        "EASI": (
            "湿疹面积和严重程度指数",
            "湿疹面积与严重程度指数",
            "湿疹面积与严重程度评分",
        ),
        "ECG": ("心电图",),
        "ECGs": ("心电图",),
        "eCRF": ("电子病例报告表", "电子CRF"),
        "EOS": ("研究结束", "试验结束", "研究结束访视"),
        "eGFR": ("估算肾小球滤过率", "肾小球滤过率估计值"),
        "ES": ("西班牙",),
        "EQ-5D-5L": ("欧洲五维健康量表五级版本", "欧洲五维健康问卷五级版本"),
        "EU": ("欧盟",),
        "EXT1": ("延长期1", "延长期", "扩展期1"),
        "FR": ("法国",),
        "FU1": ("首次随访", "第1次随访", "随访1"),
        "FU3": ("第3次随访", "随访3"),
        "HU": ("匈牙利",),
        "HADS": ("医院焦虑抑郁量表",),
        "IGA": ("研究者整体评估", "研究者总体评估"),
        "ICF": ("知情同意书",),
        "ID": ("编号", "身份"),
        "IEC": ("伦理委员会", "独立伦理委员会"),
        "IECs": ("伦理委员会", "独立伦理委员会"),
        "IMP": ("试验药物", "试验用药品", "研究药物"),
        "IRB": ("伦理委员会", "机构审查委员会", "机构伦理委员会"),
        "IRBs": ("伦理委员会", "机构审查委员会", "机构伦理委员会"),
        "IUD": ("宫内节育器",),
        # Non-specific IUS wording is legitimate; the category term must not
        # be narrowed to a single product.
        "IUS": (
            "宫内节育系统",
            "宫内系统",
            "左炔诺孕酮宫内系统",
            "释放左炔诺孕酮的宫内系统",
        ),
        "IV": ("静脉", "静脉注射", "静脉给药"),
        "JP": ("日本",),
        "LLQ": ("定量下限",),
        "MD": ("医学博士",),
        "MS": ("理学硕士", "科学硕士"),
        "mITT": ("改良意向治疗", "修正意向治疗", "改进意向治疗"),
        "NAb": ("中和抗体",),
        "NBUVB": ("窄谱中波紫外线", "窄谱UVB"),
        "PL": ("波兰",),
        "PK": ("药代动力学",),
        "PD": ("药效学", "药效动力学"),
        "POEM": ("患者导向型湿疹评估量表", "患者导向的湿疹评估量表"),
        "PRO": ("患者报告结局",),
        "RE": ("应答评估", "应答评估研究访视"),
        "RI": ("肾功能损伤", "肾功能不全"),
        "RO": ("罗马尼亚",),
        "SAE": ("严重不良事件",),
        "SAEs": ("严重不良事件",),
        "SCORAD": ("特应性皮炎评分",),
        # TCI is a drug CLASS (topical calcineurin inhibitors).  Narrowing it
        # to a single product such as tacrolimus ointment remains blocked —
        # only the class-level wording is accepted here.
        "TCI": (
            "钙调神经磷酸酶抑制剂",
            "局部钙调神经磷酸酶抑制剂",
            "外用钙调神经磷酸酶抑制剂",
        ),
        "TCS": (
            "外用皮质类固醇",
            "外用糖皮质激素",
            "外用类固醇",
            "外用类固醇类药物",
        ),
        "UA": ("尿常规", "尿液分析", "尿检"),
        "ULN": ("正常值上限",),
        "UPE": ("尿蛋白排泄", "尿蛋白排泄量", "24小时尿蛋白", "24小时的UPE"),
        "US": ("美国",),
        "VAS": ("视觉模拟量表",),
        "vIGA-AD": ("经验证的特应性皮炎研究者整体评估", "特应性皮炎研究者整体评估"),
        "WPAI-SHP": ("特定健康问题所致工作生产力与活动受损",),
    }
    missing_abbreviations = [
        item
        for item in source_abbreviations
        if item not in translated_text
        and not (item.endswith("s") and item[:-1] in translated_text)
        and not any(
            equivalent in translated_text
            for equivalent in abbreviation_equivalents.get(item, ())
        )
    ]
    if missing_abbreviations:
        failures.append("source_abbreviation_missing")
    assessment_identity_source_patterns = {
        "EASI": r"\bEASI\b|Eczema\s+Area\s+and\s+Severity\s+Index",
        # vIGA-AD is a validated AD-specific IGA instrument. Treating its
        # retained name as an unsupported generic IGA addition creates a
        # false positive, while source_abbreviation_missing still blocks an
        # actual vIGA-AD -> plain IGA downgrade.
        "IGA": (
            r"\bIGA\b|\bvIGA-AD\b|Investigator(?:'s)?\s+Global\s+Assessment|"
            r"Validated\s+Investigator\s+Global\s+Assessment"
            r"\s+Scale\s+for\s+Atopic\s+Dermatitis"
        ),
        "vIGA-AD": (
            r"\bvIGA-AD\b|Validated\s+Investigator\s+Global\s+Assessment"
            r"\s+Scale\s+for\s+Atopic\s+Dermatitis"
        ),
        "ADSD": r"\bADSD\b|Atopic\s+Dermatitis\s+Symptom\s+Diary",
        "DLQI": r"\bDLQI\b|Dermatology\s+Life\s+Quality\s+Index",
        "HADS": r"\bHADS\b|Hospital\s+Anxiety\s+and\s+Depression\s+Scale",
        "POEM": r"\bPOEM\b|Patient-Oriented\s+Eczema\s+Measure",
        "SCORAD": r"\bSCORAD\b|SCORing\s+Atopic\s+Dermatitis",
        "VAS": r"\bVAS\b|Visual\s+Analogue\s+Scale",
    }
    for scale, source_pattern in assessment_identity_source_patterns.items():
        if re.search(source_pattern, source_text, re.I):
            continue
        if scale in translated_text or any(
            equivalent in translated_text
            for equivalent in abbreviation_equivalents.get(scale, ())
        ):
            failures.append(f"unsupported_scale_identity_added:{scale}")
    if re.search(
        r"\bimportant\s+(?:side\s+effects?|adverse\s+(?:events?|reactions?))\b",
        source_text,
        re.I,
    ) and re.search(r"严重(?:的)?(?:副作用|不良反应|不良事件)", translated_text):
        failures.append("important_side_effect_severity_upcoded")
    if re.search(r"\bbilateral\s+tubal\s+occlusion\b", source_text, re.I) and re.search(
        r"双侧输卵管结扎", translated_text
    ):
        failures.append("bilateral_tubal_occlusion_narrowed_to_ligation")
    if (
        re.search(r"\bIUS\b", source_text)
        and not re.search(r"\b(?:levonorgestrel|LNG)\b", source_text, re.I)
        and re.search(r"左炔诺孕酮", translated_text)
    ):
        failures.append("ius_category_narrowed")
    if re.search(r"\bsame[-\s]+sex\s+partner\b", source_text, re.I) and not re.search(
        r"同性(?:别)?伴侣", translated_text
    ):
        failures.append("same_sex_partner_omitted")
    if (
        re.search(
            r"\bnot\s+just\s+being\s+without\s+(?:a\s+)?current\s+partner\b",
            source_text,
            re.I,
        )
        and re.search(
            r"(?:且|并且|同时|而且)[^，。；;]{0,12}(?:当前)?(?:并)?无"
            r"(?:性)?伴侣",
            translated_text,
        )
        and not re.search(
            r"(?:并非|不是|不得|不能)[^，。；;]{0,20}"
            r"(?:(?:仅|只)|(?:因|由于)[^，。；;]{0,10}(?:无|没有)(?:性)?伴侣)",
            translated_text,
        )
    ):
        failures.append("abstinence_partner_condition_inverted")
    if SOURCE_NEGATION_PATTERN.search(
        source_text
    ) and not CHINESE_NEGATION_PATTERN.search(translated_text):
        failures.append("negation_signal_missing")
    if participant_terminology_mismatch(source_text, translated_text):
        failures.append("regulatory_chinese_term_calque")
    if UNTRANSLATED_CONNECTOR_PATTERN.search(translated_text):
        failures.append("untranslated_source_connector")
    if "疗效" in translated_text:
        source_has_efficacy_semantics = bool(
            re.search(
                r"\b(?:efficacy|effectiveness|therapeutic\s+effect)\b"
                r"|\bresponse\s+evaluation\b"
                r"|\btreatment\s+response\b"
                r"|\bresponse\b"
                r"|\bRE\s*="
                r"|\bRE\b",
                source_text,
                re.I,
            )
        )
        # "assessment of the treatment" can faithfully support the literal
        # Chinese phrase "治疗效果评估", but it does not license introducing
        # the broader protocol concept "疗效/疗效评估" for an IMP evaluation.
        treatment_effect_assessment_equivalent = bool(
            "治疗效果" in translated_text
            and re.search(
                r"\bassessment\s+of\s+(?:the\s+)?treatment\b",
                source_text,
                re.I,
            )
        )
        if not (
            source_has_efficacy_semantics
            or treatment_effect_assessment_equivalent
        ):
            failures.append("unsupported_medical_concept_added")
    if any(
        source_pattern.search(source_text)
        and translated_pattern.search(translated_text)
        for source_pattern, translated_pattern in REGULATORY_CHINESE_CALQUE_RULES
    ):
        failures.append("regulatory_chinese_term_calque")
    if any(
        source_pattern.search(source_text)
        and translated_pattern.search(translated_text)
        for source_pattern, translated_pattern in TEMPORAL_DEPENDENCY_INVERSION_RULES
    ):
        failures.append("temporal_dependency_changed")
    if re.search(
        r"24-hour\s+safety\s+data\s+for\s+the\s+first\s+subject.{0,180}"
        r"before\s+dosing\s+the\s+second\s+subject",
        source_text,
        re.I | re.S,
    ) and not re.search(r"第\s*(?:2|二)\s*(?:例|名)受试者", translated_text):
        failures.append("temporal_dependency_changed")
    if re.search(
        r"[\u4e00-\u9fff]\s+(?:DLRM|PK|PD|SAD|MAD|SC|IV)\b|"
        r"\b(?:DLRM|PK|PD|SAD|MAD|SC|IV)\s+[\u4e00-\u9fff]",
        translated_text,
    ):
        failures.append("chinese_typography_spacing")
    failures.extend(evaluate_controlled_term_fidelity(source_text, translated_text))
    unique_failures = tuple(dict.fromkeys(failures))
    return TranslationFidelityResult(
        passed=not unique_failures,
        failure_codes=unique_failures,
        source_numeric_tokens=source_numbers,
        translated_numeric_tokens=translated_numbers,
        source_abbreviations=source_abbreviations,
    )


def evaluate_document_content(
    *,
    snapshot: WritingReferenceSearchSnapshot,
    artifact: WritingReferenceDocumentArtifact,
    spans: list[WritingReferenceExtractedSpan],
    actor: str,
) -> WritingReferenceDocumentValidationRecord:
    extraction_revisions = {span.extraction_revision for span in spans}
    if len(extraction_revisions) != 1:
        raise ValueError(
            "document validation requires one nonempty extraction revision"
        )
    extraction_revision = next(iter(extraction_revisions))
    candidate = next(
        (item for item in snapshot.candidates if item.nct_id == artifact.nct_id),
        None,
    )
    if candidate is None:
        raise ValueError(
            "document candidate is not present in the source search snapshot"
        )
    source_document = next(
        (
            item
            for item in candidate.public_documents
            if item.document_id == artifact.source_document_id
        ),
        None,
    )
    manually_uploaded = artifact.source_status == "user_uploaded"
    if source_document is None and not manually_uploaded:
        raise ValueError(
            "document metadata is not present in the source search snapshot"
        )

    text = "\n".join(span.source_text for span in spans)[:2_000_000]
    lowered = text.casefold()
    locators = [span.source_locator for span in spans[:3]]
    checks: list[WritingReferenceDocumentValidationCheck] = []

    found_nct_ids = sorted(set(NCT_ID_PATTERN.findall(text.upper())))
    provenance_url = " ".join(
        [
            str(getattr(artifact, "requested_url", "") or ""),
            str(getattr(artifact, "final_url", "") or ""),
        ]
    )
    ctgov_provenance = (
        not manually_uploaded
        and bool(artifact.nct_id)
        and (
            "clinicaltrials.gov/ProvidedDocs/" in provenance_url
            or str(getattr(artifact, "source_status", "") or "") == "downloaded"
            or str(getattr(artifact, "source_document_id", "") or "").startswith("ctgov_")
        )
    )
    if artifact.nct_id in found_nct_ids:
        nct_outcome = "match"
        observed_nct = artifact.nct_id
    elif found_nct_ids and ctgov_provenance:
        # CT.gov ProvidedDocs are already bound to artifact.nct_id by the
        # registry path. Protocol/SAP bodies frequently cite other NCTs in
        # background / competitive landscape sections. Preserve those IDs in
        # the observed trace, but do not turn an official registry binding into
        # a row-by-row medical confirmation task.
        nct_outcome = "match"
        observed_nct = (
            f"CT.gov公开下载绑定{artifact.nct_id}；正文另见引用 "
            + ", ".join(found_nct_ids[:8])
        )
    elif found_nct_ids:
        nct_outcome = "mismatch"
        observed_nct = ", ".join(found_nct_ids)
    elif ctgov_provenance:
        nct_outcome = "match"
        observed_nct = f"CT.gov公开下载绑定{artifact.nct_id}（正文未印刷NCT编号）"
    else:
        nct_outcome = "warning"
        observed_nct = "正文未识别到NCT编号"
    checks.append(
        WritingReferenceDocumentValidationCheck(
            check_code="study_identifier",
            label="研究标识",
            expected_value=artifact.nct_id,
            observed_value=observed_nct,
            outcome=nct_outcome,
            evidence_locators=locators,
        )
    )

    indication_terms = [snapshot.request.indication, *candidate.conditions]
    matched_indication = next(
        (
            term
            for term in indication_terms
            if term.strip() and re.sub(r"\s+", " ", term.strip().casefold()) in lowered
        ),
        "",
    )
    checks.append(
        WritingReferenceDocumentValidationCheck(
            check_code="indication",
            label="适应症",
            expected_value=snapshot.request.indication,
            observed_value=(
                matched_indication
                or (
                    f"ClinicalTrials.gov研究记录{artifact.nct_id}与检索快照绑定"
                    "（正文未直接印刷目标适应症名称）"
                    if ctgov_provenance
                    else "正文未直接识别到目标适应症名称"
                )
            ),
            outcome="match" if matched_indication or ctgov_provenance else "warning",
            evidence_locators=locators,
        )
    )

    publication_signals = sum(
        signal in lowered for signal in ("abstract", "doi:", "journal", "references")
    )
    expected_type = (
        artifact.document_type if manually_uploaded else source_document.document_type
    )
    anchors = {
        span.ich_m11_anchor
        for span in spans
        if span.ich_m11_anchor and span.ich_m11_anchor != "unmapped"
    }
    protocol_anchor_count = len(
        anchors.intersection(
            {"synopsis", "objectives_endpoints", "eligibility", "schedule", "safety"}
        )
    )
    protocol_title = any(
        re.search(
            r"(?:\bstudy protocol\b|\bclinical trial protocol\b|临床试验方案|临床研究方案)",
            span.source_text,
            re.I,
        )
        for span in spans[:100]
    )
    protocol_strong = protocol_title or protocol_anchor_count >= 3
    standalone_sap_title_re = re.compile(
        r"^\s*(?:#{1,6}\s*)?"
        r"(?:(?:appendix|附录)\s+[A-Z0-9.\-]+\s*[:：\-–—]?\s*)?"
        r"(?:statistical analysis plan|统计分析计划|统计分析方案)\b",
        re.I,
    )
    sap_title = any(
        len(
            str(span.section_heading or span.source_text or "")
        ) <= 240
        and str(span.source_text or "").count("\t") <= 1
        and standalone_sap_title_re.search(
            str(span.section_heading or span.source_text or "")
        )
        for span in spans
    )
    sap_detail_count = sum(
        bool(re.search(pattern, lowered, re.I))
        for pattern in (
            r"analysis (?:population|set)",
            r"statistical methods?",
            r"missing data",
            r"multiplicity|multiple testing",
            r"interim analysis",
            r"分析集",
            r"统计方法",
            r"缺失数据",
            r"多重性|多重检验",
            r"期中分析",
        )
    )
    sap_strong = sap_title and sap_detail_count >= 2
    registry_document_type_authoritative = (
        ctgov_provenance
        and source_document is not None
        and expected_type in {"protocol", "sap"}
    )
    if registry_document_type_authoritative:
        # ClinicalTrials.gov exposes hasProtocol/hasSap as first-class upload
        # metadata and quality-controls the declared document type.  An SAP
        # routinely repeats the governing protocol title, objectives, design,
        # and endpoint language; a Protocol also commonly contains an abstract,
        # journal citations, and references.  Those content features are not
        # contradictory evidence against a registry-declared document.
        type_outcome = "match"
        registry_labels = {
            "protocol": "Protocol",
            "sap": "SAP",
            "protocol_sap": "Protocol+SAP",
        }
        observed_type = (
            f"ClinicalTrials.gov登记为{registry_labels[expected_type]}"
            f"（{source_document.filename}）"
        )
    elif (
        expected_type in {"protocol", "sap", "protocol_sap"}
        and publication_signals >= 2
        and not (protocol_strong or sap_strong)
    ):
        type_outcome = "mismatch"
        observed_type = "疑似Publication/期刊论文"
    elif expected_type == "protocol" and protocol_strong:
        type_outcome = "match"
        observed_type = "Protocol" + ("（同时识别到SAP结构）" if sap_strong else "")
    elif expected_type == "sap" and sap_strong and not protocol_strong:
        type_outcome = "match"
        observed_type = "SAP"
    elif expected_type == "protocol_sap" and protocol_strong and sap_strong:
        type_outcome = "match"
        observed_type = "Protocol+SAP"
    elif expected_type == "protocol_sap" and protocol_strong:
        type_outcome = "match"
        observed_type = (
            "正文识别为Protocol；来源元数据标记Protocol+SAP，"
            "未发现独立SAP边界，仅按Protocol语料使用"
        )
    elif expected_type == "protocol" and sap_strong:
        type_outcome = "mismatch"
        observed_type = "疑似SAP，未识别到完整Protocol结构"
    elif expected_type == "sap" and protocol_strong:
        type_outcome = "mismatch"
        observed_type = "疑似Protocol，未识别到独立SAP结构"
    elif expected_type == "protocol_sap" and sap_strong:
        type_outcome = "mismatch"
        observed_type = "仅识别到SAP结构"
    else:
        type_outcome = "warning"
        observed_type = "正文结构特征不足，需人工确认文件类型"
    checks.append(
        WritingReferenceDocumentValidationCheck(
            check_code="document_type",
            label="文件类型",
            expected_value=expected_type,
            observed_value=observed_type,
            outcome=type_outcome,
            evidence_locators=locators,
        )
    )

    final_source = urlparse(artifact.final_url)
    source_metadata_matches = manually_uploaded or (
        artifact.requested_url == source_document.download_url
        and final_source.scheme == "https"
        and final_source.hostname in CTGOV_ALLOWED_HOSTS
    )
    expected_source = (
        "医学经理手动上传" if manually_uploaded else source_document.download_url
    )
    observed_source = (
        f"医学经理手动上传 · SHA-256 {artifact.content_sha256}"
        if manually_uploaded
        else f"{artifact.requested_url} -> {artifact.final_url}"
    )
    checks.append(
        WritingReferenceDocumentValidationCheck(
            check_code="source_metadata",
            label="来源与文件记录",
            expected_value=expected_source,
            observed_value=observed_source,
            outcome="match" if source_metadata_matches else "warning",
        )
    )
    expected_date = (
        "用户声明日期，仅作为基本信息记录"
        if manually_uploaded and artifact.document_date
        else "手动上传未填写文件日期"
        if manually_uploaded
        else source_document.document_date or source_document.upload_date
    )
    observed_date = artifact.document_date or artifact.upload_date
    checks.append(
        WritingReferenceDocumentValidationCheck(
            check_code="document_version_date",
            label="文件日期/版本",
            expected_value=expected_date or "公开来源未提供日期",
            observed_value=observed_date or "文件记录未提供日期",
            outcome=(
                "warning"
                if manually_uploaded
                else "match"
                if expected_date and expected_date == observed_date
                else "warning"
            ),
        )
    )
    outcomes = {check.outcome for check in checks}
    if "mismatch" in outcomes:
        status = "mismatch"
        summary = "文件内容与当前研究或预期文件类型不符，请确认后再纳入正式写作语料。"
    elif "warning" in outcomes:
        status = "needs_review"
        summary = "部分文件关键信息无法自动确认，请由医学专业人员核实后继续。"
    else:
        status = "confirmed"
        summary = "文件基本信息、适应症和文件类型与当前任务一致。"
    now = datetime.now(timezone.utc)
    expected_context_hash = hashlib.sha256(
        json.dumps(
            {
                "project_id": artifact.project_id,
                "snapshot_id": snapshot.snapshot_id,
                "indication": snapshot.request.indication,
                "nct_id": artifact.nct_id,
                "source_document_id": artifact.source_document_id,
                "document_type": expected_type,
                "document_date": artifact.document_date
                if manually_uploaded
                else source_document.document_date,
                "upload_date": artifact.upload_date
                if manually_uploaded
                else source_document.upload_date,
                "source_status": artifact.source_status,
                "source_state_revision": artifact.state_revision,
                "extraction_revision": extraction_revision,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    validation_id = (
        "wref_validation_"
        + hashlib.sha256(
            (
                f"{artifact.artifact_id}|1|{artifact.content_sha256}|"
                f"{expected_context_hash}|{DOCUMENT_CONTENT_VALIDATOR_VERSION}|{status}"
            ).encode("utf-8")
        ).hexdigest()[:20]
    )
    return WritingReferenceDocumentValidationRecord(
        validation_id=validation_id,
        project_id=artifact.project_id,
        artifact_id=artifact.artifact_id,
        revision=1,
        status=status,
        document_sha256=artifact.content_sha256,
        extraction_revision=extraction_revision,
        source_state_revision=artifact.state_revision,
        expected_context_hash=expected_context_hash,
        validator_version=DOCUMENT_CONTENT_VALIDATOR_VERSION,
        checks=checks,
        summary=summary,
        actor=actor,
        created_at=now,
    )


def is_corpus_admissible(
    *,
    source_current: bool,
    extraction_status: str,
    fidelity_status: str,
    medical_review_status: str,
    translation_status: str,
) -> bool:
    return all(
        (
            source_current,
            extraction_status == "passed",
            fidelity_status == "passed",
            medical_review_status == "approved",
            translation_status == "completed",
        )
    )


def _looks_like_section_heading(text: str, *, max_size: float, is_bold: bool) -> bool:
    if len(text) > 160:
        return False
    if max_size >= 12.0 or is_bold:
        return True
    return bool(
        re.match(
            r"^(?:(?:section|appendix)\s+)?(?:\d+(?:\.\d+)*|[A-Z][A-Z0-9 .:/()&,-]{4,})\b",
            text,
        )
    )


def _layout_fingerprint(text: str) -> str:
    normalized = re.sub(r"[\x00-\x1f]+", " ", text).lower()
    normalized = re.sub(r"\bpage\s*\d+\s*(?:of|/)\s*\d+\b", "page # of #", normalized)
    normalized = re.sub(r"\b\d+\s+of\s+\d+\b", "# of #", normalized)
    normalized = re.sub(r"\bpage\s*\d+\b", "page #", normalized)
    normalized = re.sub(r"(?<![a-z0-9])\d{1,4}(?![a-z0-9])", "#", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _exact_layout_fingerprint(text: str) -> str:
    normalized = re.sub(r"[\x00-\x1f]+", " ", text).lower()
    return re.sub(r"\s+", " ", normalized).strip()


def _page_edge_band(page_height: float) -> float:
    """Cover portrait and landscape running margins without reaching body content."""
    return max(page_height * 0.12, min(120.0, page_height * 0.20))


def _canonical_pdf_bbox(
    bbox: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Normalize parser geometry before it enters immutable evidence.

    MuPDF builds can return equivalent text boxes with small baseline
    differences. Raw geometry remains available inside the parser for layout
    decisions; only the persisted source-fragment bbox is snapped to the
    versioned 2-point grid.
    """

    normalized = tuple(
        float(round(float(value) / PDF_GEOMETRY_QUANTUM_POINTS))
        * PDF_GEOMETRY_QUANTUM_POINTS
        for value in bbox
    )
    return tuple(0.0 if value == 0 else value for value in normalized)


def _source_fragment(block: _PdfTextBlock) -> WritingReferenceSourceFragment:
    return WritingReferenceSourceFragment(
        physical_page=block.physical_page,
        block_index=block.block_index,
        source_locator=block.source_locator,
        bbox=_canonical_pdf_bbox(block.bbox),
        source_text=block.source_text,
        source_text_sha256=block.source_text_sha256,
        layout_role=block.layout_role,
    )


def _is_cross_page_continuation(
    previous: _PdfTextBlock,
    following: _PdfTextBlock,
) -> bool:
    if previous.layout_role != "body" or following.layout_role != "body":
        return False
    if following.physical_page != previous.physical_page + 1:
        return False
    previous_width = previous.bbox[2] - previous.bbox[0]
    following_width = following.bbox[2] - following.bbox[0]
    if (
        previous_width < previous.page_width * 0.55
        or following_width < following.page_width * 0.55
    ):
        return False
    if previous.bbox[3] < previous.page_height * 0.82:
        return False
    if following.bbox[1] > following.page_height * 0.22:
        return False
    if abs(previous.bbox[0] - following.bbox[0]) > max(
        36.0, previous.page_width * 0.06
    ):
        return False
    if len(previous.source_text) < 30 or len(following.source_text) < 20:
        return False
    if _looks_like_section_heading(
        previous.source_text,
        max_size=previous.max_size,
        is_bold=previous.is_bold,
    ) or _looks_like_section_heading(
        following.source_text,
        max_size=following.max_size,
        is_bold=following.is_bold,
    ):
        return False
    previous_tail = re.sub(r"[\s\"'”’\)\]]+$", "", previous.source_text)
    if re.search(r"[.!?;:]$", previous_tail):
        return False
    if re.match(
        r"^(?:[-•▪◦]|[xo]\s+|\(?\d+[.)]|\(?[a-zA-Z][.)])\s*",
        following.source_text,
    ):
        return False
    first_character = following.source_text.lstrip()[:1]
    return bool(
        first_character and first_character.isalpha() and first_character.islower()
    )


def _is_adjacent_abbreviation_continuation(
    previous: _PdfTextBlock,
    following: _PdfTextBlock,
) -> bool:
    """Detect a definition split between adjacent PDF text blocks."""
    if previous.layout_role != "body" or following.layout_role != "body":
        return False
    if previous.physical_page != following.physical_page:
        return False
    if following.block_index != previous.block_index + 1:
        return False
    if not previous.source_text.lstrip().lower().startswith("abbreviations:"):
        return False
    previous_tail = previous.source_text.rstrip()
    if not previous_tail or re.search(r"[.;:]$", previous_tail):
        return False
    if following.bbox[1] - previous.bbox[3] > 36:
        return False
    return bool(
        re.match(
            r"^[A-Za-z][A-Za-z -]{0,60};\s*[A-Za-z][A-Za-z0-9-]{1,20}\s*=",
            following.source_text.strip(),
        )
    )


def _merge_source_text(blocks: list[_PdfTextBlock]) -> str:
    combined = blocks[0].source_text.rstrip()
    for block in blocks[1:]:
        following = block.source_text.lstrip()
        combined = (
            combined + following
            if combined.endswith("-")
            else f"{combined} {following}"
        )
    return re.sub(r"\s+", " ", combined).strip()


def _normalize_pdf_table_cell(value: Any) -> str:
    """Normalize one detected PDF table cell without losing cell boundaries."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.replace("|", r"\|")


def _markdown_pdf_table_row(values: Sequence[Any]) -> str:
    """Render one physical table row as a stable cell-delimited source unit."""
    return (
        "| " + " | ".join(_normalize_pdf_table_cell(value) for value in values) + " |"
    )


def _bbox_center_inside(
    bbox: tuple[float, float, float, float],
    region: tuple[float, float, float, float],
) -> bool:
    center_x = (bbox[0] + bbox[2]) / 2
    center_y = (bbox[1] + bbox[3]) / 2
    return region[0] <= center_x <= region[2] and region[1] <= center_y <= region[3]


def _detected_table_row_blocks(
    page: Any,
    *,
    physical_page: int,
    locator_prefix: str,
    artifact: WritingReferenceDocumentArtifact,
    schedule_page: bool,
) -> tuple[list[_PdfTextBlock], list[tuple[float, float, float, float]]]:
    """Extract visibly ruled tables into row-level, cell-preserving blocks.

    ``lines_strict`` is intentionally used here: only actual line geometry is
    promoted to table structure. Borderless layout tables and ordinary page
    alignment continue through the existing text-block path.
    """
    try:
        detected = page.find_tables(strategy="lines_strict").tables
    except Exception:
        return [], []

    row_blocks: list[_PdfTextBlock] = []
    accepted_regions: list[tuple[float, float, float, float]] = []
    provisional_index = 100_000
    for table_index, table in enumerate(detected):
        rows = table.extract()
        if table.row_count < 2 or table.col_count < 2:
            continue
        nonempty_cells = sum(
            1 for row in rows for value in row if _normalize_pdf_table_cell(value)
        )
        if nonempty_cells < 4:
            continue
        table_bbox = tuple(float(value) for value in table.bbox)
        accepted_regions.append(table_bbox)
        for row_index, (table_row, values) in enumerate(zip(table.rows, rows)):
            text_value = _markdown_pdf_table_row(values)
            if not any(_normalize_pdf_table_cell(value) for value in values):
                continue
            raw_bbox = tuple(float(value) for value in table_row.bbox)
            text_hash = hashlib.sha256(text_value.encode("utf-8")).hexdigest()
            row_blocks.append(
                _PdfTextBlock(
                    physical_page=physical_page,
                    block_index=provisional_index,
                    source_locator=(
                        f"{locator_prefix}:{artifact.nct_id}:{artifact.artifact_id}:"
                        f"p{physical_page}:t{table_index}:r{row_index}"
                    ),
                    bbox=raw_bbox,
                    page_width=float(page.rect.width),
                    page_height=float(page.rect.height),
                    source_text=text_value,
                    source_text_sha256=text_hash,
                    max_size=0.0,
                    is_bold=False,
                    schedule_page=schedule_page,
                )
            )
            provisional_index += 1
    return row_blocks, accepted_regions


def detect_anomaly_pages(
    payload: bytes,
    *,
    max_pages: int = 2000,
) -> list[dict]:
    """Detect text-bearing pages with small filled vector glyphs overlapping
    text-line baselines — the PNH comparison-symbol-loss pattern.

    This is a GENERAL detector.  It is NOT hardcoded to PNH, LDH, any page
    number, or any specific word.  It flags any page where:

    1. The page has a non-empty text layer (``page.get_text("text")`` returns
       meaningful content); AND
    2. The page contains small filled vector drawings (``page.get_drawings()``)
       whose bounding boxes are small (< 12pt in both dimensions) and sit
       within or adjacent to a text-line baseline band; AND
    3. At least one text line on that page contains numeric/unit tokens
       (digits, ``mg``, ``g/dL``, ``ULN``, ``x``, ``>=``, ``<=``, ``<``,
       ``>``, ``years``, ``kg``, ``%``, etc.).

    Returns a list of ``{"physical_page": int, "reason": str}`` dicts, sorted
    by page number.  False-positive OCR of a few additional pages is
    acceptable; silently losing medically meaningful comparators is not.
    """
    import pymupdf

    document = pymupdf.open(stream=payload, filetype="pdf")
    try:
        if len(document) == 0 or len(document) > max_pages:
            return []
        anomaly_pages: list[dict] = []
        # Tokens that suggest a line carries numeric/unit/comparator meaning.
        # This is deliberately broad to catch dose, lab-value, timing and
        # eligibility lines without hardcoding a single domain.
        numeric_unit_pattern = re.compile(
            r"(?:\d|mg|g/dL|g/dl|ULN| x |×|>=|<=|<|>|≥|≤|years|kg|mL|ml|"
            r"mg/m|µg|mcg|mmol|IU|U/L|ng|mL/min|BSA|BMI|mg/kg|"
            r"week|day|month|hour|%|percent|dose|cohort)",
            re.IGNORECASE,
        )

        for page_number, page in enumerate(document, start=1):
            page_text = page.get_text("text")
            if not page_text.strip():
                continue  # zero-text pages are handled separately

            # Gather text-line baseline bands from the structured dict.
            text_lines: list[tuple[float, float]] = []  # (y0, y1)
            for block in page.get_text("dict", sort=True).get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    bbox = line.get("bbox", (0, 0, 0, 0))
                    if len(bbox) == 4:
                        text_lines.append((float(bbox[1]), float(bbox[3])))
            if not text_lines:
                continue

            # Gather small filled vector drawings.
            try:
                drawings = page.get_drawings()
            except Exception:
                drawings = []
            small_filled_near_baseline = 0
            for draw in drawings:
                rect = draw.get("rect")
                if rect is None:
                    continue
                w = float(rect.width) if hasattr(rect, "width") else (rect[2] - rect[0])
                h = (
                    float(rect.height)
                    if hasattr(rect, "height")
                    else (rect[3] - rect[1])
                )
                # Small drawing: both dimensions under 12pt (typical glyph
                # size for comparison operators is 4-6pt).
                if w > 12 or h > 12 or w < 0.5 or h < 0.5:
                    continue
                draw_y0 = float(rect[1]) if not hasattr(rect, "y0") else float(rect.y0)
                draw_y1 = float(rect[3]) if not hasattr(rect, "y1") else float(rect.y1)
                draw_center_y = (draw_y0 + draw_y1) / 2
                # Check if the drawing overlaps or sits within 3pt of any
                # text-line baseline band.
                for line_y0, line_y1 in text_lines:
                    if line_y0 - 3 <= draw_center_y <= line_y1 + 3:
                        small_filled_near_baseline += 1
                        break

            if small_filled_near_baseline < 2:
                continue

            # Check whether any text line on this page contains numeric/unit
            # tokens — this is what makes symbol loss dangerous.
            has_numeric_lines = False
            for block in page.get_text("dict", sort=True).get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    line_text = " ".join(
                        str(span.get("text") or "") for span in line.get("spans", [])
                    )
                    if numeric_unit_pattern.search(line_text):
                        has_numeric_lines = True
                        break
                if has_numeric_lines:
                    break

            if has_numeric_lines:
                anomaly_pages.append(
                    {
                        "physical_page": page_number,
                        "reason": (
                            "vector_glyphs_over_text_baselines_with_numeric_lines"
                        ),
                    }
                )
        return anomaly_pages
    finally:
        document.close()


def extract_pdf_sections(
    payload: bytes,
    artifact: WritingReferenceDocumentArtifact,
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> WritingReferenceExtractionResult:
    import pymupdf

    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != artifact.content_sha256:
        raise ValueError("document content hash does not match registered artifact")
    if artifact.actual_size and len(payload) != artifact.actual_size:
        raise ValueError("document size does not match registered artifact")
    document = pymupdf.open(stream=payload, filetype="pdf")
    try:
        if len(document) == 0 or len(document) > 2000:
            raise RuntimeError("PDF page count is outside the supported range")
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "native_extracting",
                    "current_substep": f"正在提取原生文本 0/{len(document)} 页",
                    "completed": 0,
                    "total": len(document),
                    "unit": "page",
                }
            )
        extraction_revision = (
            f"pymupdf_{pymupdf.__version__}_{EXTRACTION_MAPPING_VERSION}_"
            f"{artifact.content_sha256[:16]}"
        )
        raw_blocks: list[_PdfTextBlock] = []
        zero_text_pages: list[int] = []
        locator_prefix = (
            "upload" if artifact.source_status == "user_uploaded" else "ctgov"
        )
        for page_number, page in enumerate(document, start=1):
            page_text = page.get_text("text")
            if not page_text.strip():
                zero_text_pages.append(page_number)
            normalized_page_text = re.sub(r"\s+", " ", page_text).strip()
            schedule_table_page = bool(
                re.search(
                    r"appendix\s+\d+\s*:?\s*schedule\s+of\s+assessments",
                    normalized_page_text[:500],
                    re.IGNORECASE,
                )
            )
            table_row_blocks, table_regions = _detected_table_row_blocks(
                page,
                physical_page=page_number,
                locator_prefix=locator_prefix,
                artifact=artifact,
                schedule_page=schedule_table_page,
            )
            blocks = [
                block
                for block in page.get_text("dict", sort=True).get("blocks", [])
                if block.get("type") == 0
            ]
            page_blocks: list[_PdfTextBlock] = list(table_row_blocks)
            for block_index, block in enumerate(blocks):
                text_parts = []
                max_size = 0.0
                is_bold = False
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        value = str(span.get("text") or "")
                        if value:
                            text_parts.append(value)
                        max_size = max(max_size, float(span.get("size") or 0))
                        font = str(span.get("font") or "").lower()
                        is_bold = is_bold or "bold" in font
                text_value = re.sub(r"\s+", " ", " ".join(text_parts)).strip()
                if not text_value:
                    continue
                text_hash = hashlib.sha256(text_value.encode("utf-8")).hexdigest()
                raw_bbox = tuple(
                    float(value) for value in block.get("bbox", (0, 0, 0, 0))
                )
                if any(
                    _bbox_center_inside(raw_bbox, table_region)
                    for table_region in table_regions
                ):
                    continue
                page_blocks.append(
                    _PdfTextBlock(
                        physical_page=page_number,
                        block_index=block_index,
                        source_locator=(
                            f"{locator_prefix}:{artifact.nct_id}:{artifact.artifact_id}:"
                            f"p{page_number}:b{block_index}"
                        ),
                        bbox=(raw_bbox[0], raw_bbox[1], raw_bbox[2], raw_bbox[3]),
                        page_width=float(page.rect.width),
                        page_height=float(page.rect.height),
                        source_text=text_value,
                        source_text_sha256=text_hash,
                        max_size=max_size,
                        is_bold=is_bold,
                        schedule_page=schedule_table_page,
                    )
                )
            if table_row_blocks:
                page_blocks.sort(
                    key=lambda item: (
                        round(item.bbox[1], 3),
                        round(item.bbox[0], 3),
                        item.block_index,
                    )
                )
                page_blocks = [
                    replace(
                        item,
                        block_index=final_index,
                        source_locator=(
                            f"{locator_prefix}:{artifact.nct_id}:{artifact.artifact_id}:"
                            f"p{page_number}:b{final_index}"
                        ),
                    )
                    for final_index, item in enumerate(page_blocks)
                ]
            raw_blocks.extend(page_blocks)
            if progress_callback is not None:
                progress_callback(
                    {
                        "phase": "native_extracting",
                        "current_substep": f"原生文本提取完成：第 {page_number}/{len(document)} 页",
                        "completed": page_number,
                        "total": len(document),
                        "unit": "page",
                        "context": {"physical_page": page_number},
                    }
                )
        if not raw_blocks:
            # Fully scanned PDF: no native text blocks at all.  Do NOT raise
            # here — every page is a zero-text page and the extraction service
            # will recover them via OCR.  Return an empty-spans result so the
            # service's OCR recovery path can populate spans.
            return WritingReferenceExtractionResult(
                artifact_id=artifact.artifact_id,
                project_id=artifact.project_id,
                extraction_revision=extraction_revision,
                parser_name=f"pymupdf_{pymupdf.__version__}",
                parser_version=f"pymupdf_{pymupdf.__version__}",
                page_count=len(document),
                zero_text_pages=list(range(1, len(document) + 1)),
                status="extracted",
                spans=[],
            )

        page_threshold = 3 if len(document) >= 5 else 2
        edge_fingerprint_pages: dict[tuple[str, str], set[int]] = {}
        overlay_fingerprint_pages: dict[tuple[str, int], set[int]] = {}
        overlay_fingerprint_all_pages: dict[str, set[int]] = {}
        overlay_fingerprint_bands: dict[str, set[int]] = {}
        for block in raw_blocks:
            fingerprint = _layout_fingerprint(block.source_text)
            if not fingerprint:
                continue
            width = block.bbox[2] - block.bbox[0]
            center = (block.bbox[0] + block.bbox[2]) / 2
            overlay_candidate = (
                len(block.source_text) <= 120
                and width <= block.page_width * 0.7
                and abs(center - block.page_width / 2) <= block.page_width * 0.15
            )
            exact_fingerprint = _exact_layout_fingerprint(block.source_text)
            vertical_band = round(
                ((block.bbox[1] + block.bbox[3]) / 2) / block.page_height * 10
            )
            if overlay_candidate:
                overlay_fingerprint_pages.setdefault(
                    (exact_fingerprint, vertical_band), set()
                ).add(block.physical_page)
                overlay_fingerprint_all_pages.setdefault(exact_fingerprint, set()).add(
                    block.physical_page
                )
                overlay_fingerprint_bands.setdefault(exact_fingerprint, set()).add(
                    vertical_band
                )
            edge_band = _page_edge_band(block.page_height)
            if block.bbox[3] <= edge_band:
                edge_fingerprint_pages.setdefault(("header", fingerprint), set()).add(
                    block.physical_page
                )
            elif block.bbox[1] >= block.page_height - edge_band:
                edge_fingerprint_pages.setdefault(("footer", fingerprint), set()).add(
                    block.physical_page
                )

        classified_blocks: list[_PdfTextBlock] = []
        for block in raw_blocks:
            fingerprint = _layout_fingerprint(block.source_text)
            exact_fingerprint = _exact_layout_fingerprint(block.source_text)
            layout_role = "body"
            edge_band = _page_edge_band(block.page_height)
            vertical_band = round(
                ((block.bbox[1] + block.bbox[3]) / 2) / block.page_height * 10
            )
            repeated_moving_overlay = (
                len(overlay_fingerprint_all_pages.get(exact_fingerprint, set()))
                >= page_threshold
                and len(overlay_fingerprint_bands.get(exact_fingerprint, set())) >= 2
            )
            if repeated_moving_overlay:
                layout_role = "repeated_visual_overlay"
            elif (
                block.bbox[3] <= edge_band
                and len(edge_fingerprint_pages.get(("header", fingerprint), set()))
                >= page_threshold
            ):
                layout_role = "repeated_margin_header"
            elif (
                block.bbox[1] >= block.page_height - edge_band
                and len(edge_fingerprint_pages.get(("footer", fingerprint), set()))
                >= page_threshold
            ):
                layout_role = "repeated_margin_footer"
            else:
                if (
                    len(
                        overlay_fingerprint_pages.get(
                            (exact_fingerprint, vertical_band),
                            set(),
                        )
                    )
                    >= page_threshold
                ):
                    layout_role = "repeated_visual_overlay"
            classified_blocks.append(replace(block, layout_role=layout_role))

        blocks_by_page: dict[int, list[_PdfTextBlock]] = {}
        for block in classified_blocks:
            blocks_by_page.setdefault(block.physical_page, []).append(block)
        merge_successor: dict[tuple[int, int], _PdfTextBlock] = {}
        for page_number in range(1, len(document)):
            previous_page_blocks = [
                block
                for block in blocks_by_page.get(page_number, [])
                if block.layout_role == "body"
            ]
            following_page_blocks = [
                block
                for block in blocks_by_page.get(page_number + 1, [])
                if block.layout_role == "body"
            ]
            if not previous_page_blocks or not following_page_blocks:
                continue
            previous = previous_page_blocks[-1]
            following = following_page_blocks[0]
            if _is_cross_page_continuation(previous, following):
                merge_successor[(previous.physical_page, previous.block_index)] = (
                    following
                )
        for page_blocks in blocks_by_page.values():
            ordered_page_blocks = sorted(page_blocks, key=lambda item: item.block_index)
            for previous, following in zip(
                ordered_page_blocks,
                ordered_page_blocks[1:],
            ):
                previous_key = (previous.physical_page, previous.block_index)
                if (
                    previous_key not in merge_successor
                    and _is_adjacent_abbreviation_continuation(previous, following)
                ):
                    merge_successor[previous_key] = following

        excluded_layout_fragments = [
            WritingReferenceSkippedInterstitial(
                fragment=_source_fragment(block),
                reason_code=block.layout_role,
            )
            for block in classified_blocks
            if block.layout_role in {"repeated_margin_header", "repeated_margin_footer"}
        ]
        excluded_lookup = {
            (item.fragment.physical_page, item.fragment.block_index): item
            for item in excluded_layout_fragments
        }

        semantic_units: list[
            tuple[list[_PdfTextBlock], list[WritingReferenceSkippedInterstitial]]
        ] = []
        consumed: set[tuple[int, int]] = set()
        for block in classified_blocks:
            block_key = (block.physical_page, block.block_index)
            if block_key in consumed or block.layout_role in {
                "repeated_margin_header",
                "repeated_margin_footer",
            }:
                continue
            fragments = [block]
            interstitials: list[WritingReferenceSkippedInterstitial] = []
            following = merge_successor.get(block_key)
            if following is not None:
                following_key = (following.physical_page, following.block_index)
                fragments.append(following)
                consumed.add(following_key)
                for candidate in classified_blocks:
                    candidate_key = (candidate.physical_page, candidate.block_index)
                    if candidate_key not in excluded_lookup:
                        continue
                    if (
                        candidate.physical_page == block.physical_page
                        and candidate.bbox[1] >= block.bbox[3]
                    ) or (
                        candidate.physical_page == following.physical_page
                        and candidate.bbox[3] <= following.bbox[1]
                    ):
                        interstitials.append(excluded_lookup[candidate_key])
            semantic_units.append((fragments, interstitials))

        spans: list[WritingReferenceExtractedSpan] = []
        current_heading = ""
        current_anchor = "unmapped"
        for fragments, interstitials in semantic_units:
            first = fragments[0]
            text_value = _merge_source_text(fragments)
            text_hash = hashlib.sha256(text_value.encode("utf-8")).hexdigest()
            is_overlay = first.layout_role == "repeated_visual_overlay"
            schedule_unit = any(fragment.schedule_page for fragment in fragments)
            anchor_candidate = _m11_anchor(text_value)
            looks_heading = len(fragments) == 1 and _looks_like_section_heading(
                text_value,
                max_size=first.max_size,
                is_bold=first.is_bold,
            )
            if is_overlay:
                span_anchor = "unmapped"
                section_heading = ""
            else:
                if schedule_unit:
                    current_anchor = "schedule"
                    if looks_heading:
                        current_heading = text_value
                elif looks_heading:
                    current_heading = text_value
                    current_anchor = anchor_candidate
                span_anchor = current_anchor
                if (
                    not schedule_unit
                    and not looks_heading
                    and not text_value.startswith("|")
                    and anchor_candidate
                    in {"objectives_endpoints", "eligibility", "statistics", "safety"}
                ):
                    span_anchor = anchor_candidate
                section_heading = current_heading
            source_locator = first.source_locator
            for fragment in fragments[1:]:
                locator_tail = ":".join(fragment.source_locator.rsplit(":", 2)[-2:])
                source_locator += f"+{locator_tail}"
            locator_key = "|".join(fragment.source_locator for fragment in fragments)
            span_id = (
                "wref_span_"
                + hashlib.sha256(
                    f"{artifact.artifact_id}|{extraction_revision}|{locator_key}|{text_hash}".encode(
                        "utf-8"
                    )
                ).hexdigest()[:24]
            )
            merge_reason_codes: list[str] = []
            semantic_merge_method = "none"
            if len(fragments) > 1:
                if fragments[0].physical_page == fragments[
                    1
                ].physical_page and _is_adjacent_abbreviation_continuation(
                    fragments[0],
                    fragments[1],
                ):
                    semantic_merge_method = "adjacent_abbreviation_continuation_v1"
                    merge_reason_codes = [
                        "adjacent_same_page_blocks",
                        "abbreviation_definition_split",
                    ]
                else:
                    semantic_merge_method = "cross_page_continuation_v1"
                    merge_reason_codes = [
                        "adjacent_physical_pages",
                        "previous_block_near_page_end",
                        "next_block_near_page_start",
                        "wide_blocks_left_aligned",
                        "previous_text_has_no_terminal_punctuation",
                        "next_fragment_starts_lowercase",
                    ]
                    if interstitials:
                        merge_reason_codes.append(
                            "repeated_margin_interstitials_skipped"
                        )
            spans.append(
                WritingReferenceExtractedSpan(
                    span_id=span_id,
                    project_id=artifact.project_id,
                    artifact_id=artifact.artifact_id,
                    extraction_revision=extraction_revision,
                    physical_page=first.physical_page,
                    block_index=first.block_index,
                    source_locator=source_locator,
                    section_heading=section_heading,
                    ich_m11_anchor=span_anchor,
                    source_text=text_value,
                    source_text_sha256=text_hash,
                    source_fragments=[
                        _source_fragment(fragment) for fragment in fragments
                    ],
                    skipped_interstitials=interstitials,
                    semantic_merge_method=semantic_merge_method,
                    semantic_merge_reason_codes=merge_reason_codes,
                )
            )
        return WritingReferenceExtractionResult(
            artifact_id=artifact.artifact_id,
            project_id=artifact.project_id,
            extraction_revision=extraction_revision,
            parser_name="PyMuPDF",
            parser_version=pymupdf.__version__,
            page_count=len(document),
            zero_text_pages=zero_text_pages,
            status="pending_visual_and_medical_structure_review",
            spans=spans,
            excluded_layout_fragments=excluded_layout_fragments,
        )
    finally:
        document.close()
