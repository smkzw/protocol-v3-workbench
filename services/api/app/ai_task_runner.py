from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from pydantic import ValidationError

from packages.contracts.workbench_contracts import (
    AiTaskArtifact,
    AiTaskEvidenceEntry,
    AiTaskOutputValidationStatus,
    AiTaskRequest,
    AiTaskRun,
    AiTaskRunStatus,
    MedicalWritingPicosDefinition,
    MedicalWritingStudyFraming,
)

from .ai_gateway import (
    AiGatewayConfigurationError,
    AiPromptEnvelope,
    AiProvider,
    AiProviderRuntimeError,
    AiSourceRef,
    AiTaskSpec,
    AiTaskType,
    DisabledAiProvider,
    PromptRegistry,
    PROTOCOL_SYNOPSIS_INSTRUMENT_ENDPOINT_PATHS,
    PROTOCOL_SYNOPSIS_INSTRUMENT_KINDS,
    TASK_PURPOSES,
    configured_ai_provider_from_env,
    protocol_synopsis_assessment_instrument_contract,
    validate_ai_output,
)
from .ai_execution_policy import (
    AiExecutionPolicyDenied,
    AiExecutionPolicyResolver,
    AiExecutionResolution,
)
from .ai_runtime_settings import runtime_ai_settings_store
from .ai_role_runtime_settings import INDEPENDENT_AI_ROLE, runtime_ai_role_settings_store
from .demo_repository import DemoRepository
from .medical_writing_legacy_reference_index import parse_legacy_reference_marker
from .medical_writing_content_quality import (
    DRAFTING_PROCESS_VOCABULARY_RE,
    iter_unresolved_draft_markers,
)

LOCAL_PATH_RE = re.compile(r"/Users/[^\s\"'，,；;）)\]}]+")
SAFE_ARTIFACT_KEYS = {
    "output_hash",
    "top_level_keys",
    "finding_count",
    "evidence_span_count",
}
SAFE_ARTIFACT_OPTIONAL_KEYS = {"candidate_citation_bindings"}
EXACT_SOURCE_QUOTE_TASKS = {
    AiTaskType.MEDICAL_WRITING_REVISION,
    AiTaskType.REGULATORY_TRANSLATION_ZH,
}
MEDICAL_WRITING_BOUNDED_QUOTE_SOURCE_TYPES = {
    "approved_competitor_protocol_evidence",
    "company_protocol_reference_corpus",
    "current_project_study_definition",
    "shared_phase1_protocol_reference_corpus",
}
REGULATORY_AUTHORITY_TERMS = (
    "CDE",
    "NMPA",
    "ICH",
    "FDA",
    "EMA",
    "国家药品监督管理局",
    "药品审评中心",
)

_MEDICAL_WRITING_CONTROLLED_LABEL_PATTERNS = {
    "objective.primary": (r"主要(?:试验|研究)?目的",),
    "endpoint.primary": (r"主要(?:疗效|安全性)?终点",),
    "endpoint.key_secondary": (r"关键次要(?:疗效|安全性)?终点",),
    "endpoint.secondary": (r"(?<!关键)次要(?:疗效|安全性)?终点",),
    "endpoint.exploratory": (r"探索性(?:疗效|安全性)?终点",),
    "study.confirmatory": (r"确证性", r"确认性"),
    "study.exploratory": (r"探索(?:性)?研究", r"剂量探索(?:性)?(?:临床)?(?:研究)?"),
    "status.planned": (
        r"(?:计划|预计|拟)(?:纳入|开展|接受|进行|给予|给药|评估|观察|完成|采用|分为)",
    ),
    "status.future_commitment": (
        r"将(?:纳入|开展|接受|进行|给予|给药|评估|观察|完成|采用|分为)",
    ),
    "consent.ethics_approved": (
        r"(?:伦理委员会|伦理审查委员会|IEC|IRB)(?:已经|已)?批准",
    ),
    "investigator.certified": (r"经(?:认证|资质认证)(?:的)?研究者",),
    "comparison.superiority": (r"(?:优于|优效性|优效)",),
    "comparison.noninferiority": (r"(?:非劣效|非劣)",),
    "comparison.equivalence": (r"(?:等效性|等效)",),
    "timing.last_dose": (r"末次(?:使用)?(?:研究)?(?:药物)?(?:给药|用药)?后",),
    "timing.study_end": (r"(?:研究|试验)(?:结束|完成)后",),
}
_MEDICAL_WRITING_REQUIRED_PRESERVATION_LABELS = {"timing.last_dose"}
_MEDICAL_WRITING_POPULATION_TERMS = ("试验参与者", "受试者", "患者", "健康志愿者")
_MEDICAL_WRITING_REFERENCE_ONLY_SOURCE_TYPES = {
    "approved_competitor_protocol_evidence",
    "company_protocol_reference_corpus",
    "shared_phase1_protocol_reference_corpus",
}
_MEDICAL_WRITING_NON_CHINA_REGION_PATTERN = re.compile(
    r"(?:日本|JP|欧盟|EU|美国|US|捷克|德国|西班牙|法国|匈牙利|波兰|罗马尼亚)"
)
_MEDICAL_WRITING_CHINA_AS_POPULATION_ATTRIBUTE_RE = re.compile(
    r"中国[^，。；\n]{0,18}(?:受试者|患者|试验参与者)"
)
_MEDICAL_WRITING_PROTOCOL_REFERENCE_RE = re.compile(
    r"(?:第\s*\d+(?:\.\d+){0,5}\s*节|附录\s*\d+(?:\.\d+){0,5}|文献\s*[（(]\s*\d+\s*[）)])"
)
_MEDICAL_WRITING_NUMERIC_BOUND_RE = re.compile(
    r"(?P<prefix>至少|不少于|不低于|最短|最低|至多|不多于|不超过|最长|最高)"
    r"\s*(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>天|日|周|月|年|小时)"
    r"|(?P<number2>\d+(?:\.\d+)?)\s*(?P<unit2>天|日|周|月|年|小时)"
    r"\s*(?P<suffix>及以上|或以上|及以下|或以下)"
)
_MEDICAL_WRITING_EASI_IGA_EQUIVALENCE_RE = re.compile(
    r"(?:EASI|湿疹面积(?:和|与)严重程度指数).{0,28}"
    r"(?:相当于|等同于|等价于|对应于).{0,28}"
    r"(?:IGA|研究者(?:整体|总体)评估)",
    re.IGNORECASE,
)
_MEDICAL_WRITING_CONTRACEPTION_GROUPING_RE = re.compile(
    r"(?:禁欲|无性生活)\s*[（(][^）)]{0,100}"
    r"(?:同性(?:别)?伴侣|输精管结扎)[^）)]*[）)]"
)
_BLANK_DRAFT_PLACEHOLDER_PATTERNS = (
    r"由方案规定",
    r"见方案规定",
    r"参照方案",
    r"按方案执行",
    r"方案指定的",
    r"方案要求的",
    r"一段规定的",
    r"一定时间",
    r"指定期间",
    r"具体(?:时限|时长|阈值|界值|标准|定义).{0,8}(?:待定|规定|确认)",
)
_FULL_DRAFT_PLACEHOLDER_RE = re.compile(
    r"(?:^|[\s，。；：])(?:待补充|待确认|待定|TBD|TODO|不适用|无适用内容|由方案规定|见方案规定)(?:$|[\s，。；：])",
    re.IGNORECASE,
)
# Internal transport/test vocabulary must never leak into user-facing
# protocol prose. The evidence packet may contain these markers, but the
# generated candidate must translate the underlying fact into native
# regulatory Chinese instead of exposing implementation details.
_FULL_DRAFT_INTERNAL_TOKEN_PATTERNS = (
    re.compile(r"\bfixture\b", re.IGNORECASE),
    re.compile(r"ProtocolAssemblyPlan", re.IGNORECASE),
    re.compile(r"evidence_span_ids", re.IGNORECASE),
    re.compile(r"SECTION_ID=", re.IGNORECASE),
)
_FULL_DRAFT_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*|附录\s*[A-Z0-9一二三四五六七八九十]+)[、.．：:]?\s*[^。；\n]{1,120}\s*$"
)
_FULL_DRAFT_UNSUPPORTED_RATIONALE_RE = re.compile(
    r"尚未(?:规定|明确)|未(?:规定|提供|明确)|事实不足|来源不足|需(?:核对|确认|补充)"
)
_FULL_DRAFT_UNSUPPORTED_SPECIFIC_RULE_RE = re.compile(
    r"(?:必须立即|应立即|24\s*小时|在\s*\d+\s*(?:小时|日|天|周)内|"
    r"受试者与.{0,40}保持盲态|不得再次发放|"
    r"双盲设计要求受试者、研究者.{0,60}(?:不知晓|保持盲态)|"
    r"签署知情同意.{0,12}(?:后|起).{0,24}研究结束|"
    r"所有.{0,24}(?:均应|必须)|"
    r"(?:评估|评价)安排在(?:筛选期|基线/第1天)|"
    r"(?:实验室检查|生命体征|12导联心电图|体格检查).{0,80}第2、4、8、12、16周|"
    r"TEAE.{0,40}(?:双盲治疗期及安全性随访期|新发生或较基线加重)|"
    r"DLQI在基线及第16周|"
    r"男性受试者伴侣妊娠|(?:母亲与新生儿|新生儿健康)|"
    r"末例受试者完成第20周|"
    r"依从性评价.{0,40}(?:基线/第1天|第2、4、8、12、16周)|"
    r"不良事件指受试者.{0,60}任何不良医学事件)"
)

_MEDICAL_WRITING_NUMERIC_CITATION_RE = re.compile(
    r"[\[［]\s*\d{1,4}(?:\s*[-‐‑‒–—]\s*\d{1,4})?"
    r"(?:\s*[,，]\s*\d{1,4}(?:\s*[-‐‑‒–—]\s*\d{1,4})?)*\s*[\]］]"
)


def _numeric_citation_occurrences(text: Any) -> list[tuple[str, tuple[int, ...]]]:
    if not isinstance(text, str):
        return []
    occurrences: list[tuple[str, tuple[int, ...]]] = []
    for match in _MEDICAL_WRITING_NUMERIC_CITATION_RE.finditer(text):
        marker = match.group(0)
        numbers = parse_legacy_reference_marker(unicodedata.normalize("NFKC", marker))
        if numbers:
            occurrences.append((marker, numbers))
    return occurrences


def validate_medical_writing_candidate_citations(
    output: Dict[str, Any],
    project_reference_ids: Iterable[str],
) -> List[str]:
    """Validate model citation bindings without changing candidate prose."""
    revision = output.get("revision")
    if not isinstance(revision, dict):
        return []
    candidates: list[tuple[str, Any]] = [("revision", revision)]
    alternatives = revision.get("alternatives")
    if isinstance(alternatives, list):
        candidates.extend(
            (f"revision.alternatives[{index}]", candidate)
            for index, candidate in enumerate(alternatives)
        )
    available = set(project_reference_ids)
    errors: List[str] = []
    for prefix, candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        occurrences = _numeric_citation_occurrences(candidate.get("proposal_text"))
        bindings = candidate.get("citation_bindings")
        if not occurrences:
            if bindings not in (None, []):
                errors.append(
                    f"{prefix}.citation_bindings must be empty when proposal_text has no numeric citations"
                )
            continue
        if not isinstance(bindings, list):
            errors.append(
                f"{prefix}.citation_bindings is required for every numeric citation marker"
            )
            continue
        if len(bindings) != len(occurrences):
            errors.append(
                f"{prefix}.citation_bindings count does not match citation marker occurrences"
            )
            continue
        for index, ((marker_text, marker_numbers), binding) in enumerate(
            zip(occurrences, bindings)
        ):
            binding_prefix = f"{prefix}.citation_bindings[{index}]"
            if not isinstance(binding, dict) or set(binding) != {
                "marker_text",
                "display_numbers",
                "reference_ids",
            }:
                errors.append(f"{binding_prefix} has an invalid structured contract")
                continue
            if binding.get("marker_text") != marker_text:
                errors.append(
                    f"{binding_prefix}.marker_text does not match citation occurrence order"
                )
            display_numbers = binding.get("display_numbers")
            if (
                not isinstance(display_numbers, list)
                or any(
                    not isinstance(number, int) or isinstance(number, bool)
                    for number in display_numbers
                )
                or display_numbers != list(marker_numbers)
            ):
                errors.append(
                    f"{binding_prefix}.display_numbers does not match marker numbers and order"
                )
            reference_ids = binding.get("reference_ids")
            if (
                not isinstance(reference_ids, list)
                or len(reference_ids) != len(marker_numbers)
                or any(
                    not isinstance(reference_id, str)
                    or not re.fullmatch(r"mwref_[0-9a-f]{20}", reference_id)
                    for reference_id in reference_ids
                )
                or len(set(reference_ids)) != len(reference_ids)
            ):
                errors.append(
                    f"{binding_prefix}.reference_ids count or identity is invalid"
                )
                continue
            missing = [
                reference_id
                for reference_id in reference_ids
                if reference_id not in available
            ]
            if missing:
                errors.append(
                    f"{binding_prefix}.reference_ids are not in the current project: {missing}"
                )
    return errors


def _project_references_from_store(
    ai_store: Any,
    project_id: str,
) -> list[dict[str, str]]:
    jsonl_path = getattr(ai_store, "jsonl_path", None)
    if not isinstance(jsonl_path, Path):
        return []
    database_path = jsonl_path.parent / "medical_writing_literature.sqlite3"
    if not database_path.is_file():
        return []
    try:
        with sqlite3.connect(database_path) as connection:
            rows = connection.execute(
                """
                SELECT reference_id, payload_json
                FROM medical_writing_literature_references
                WHERE tenant_id = ? AND project_id = ?
                """,
                ("kangzhe_local", project_id),
            ).fetchall()
    except sqlite3.Error:
        return []
    references: list[dict[str, str]] = []
    for reference_id, payload_json in rows:
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            payload = {}
        references.append(
            {
                "reference_id": str(reference_id),
                "title": str(payload.get("title") or ""),
                "doi": str(payload.get("doi") or ""),
                "pmid": str(payload.get("pmid") or ""),
                "year": str(payload.get("year") or ""),
            }
        )
    return references


def _project_reference_ids_from_store(
    ai_store: Any,
    project_id: str,
) -> set[str]:
    return {
        item["reference_id"]
        for item in _project_references_from_store(ai_store, project_id)
    }


def _roman_level_ranges(
    text: str,
    *,
    ignore_region_specific: bool = False,
) -> set[tuple[str, str]]:
    pattern = re.compile(
        r"(?<![A-Za-z])([IVXLCDM]+)\s*(?:至|到|[-–—~～])\s*"
        r"([IVXLCDM]+)\s*级",
        flags=re.IGNORECASE,
    )
    ranges: set[tuple[str, str]] = set()
    for match in pattern.finditer(text):
        if ignore_region_specific:
            context = text[
                max(0, match.start() - 48) : min(len(text), match.end() + 48)
            ]
            if _MEDICAL_WRITING_NON_CHINA_REGION_PATTERN.search(context):
                continue
        ranges.add((match.group(1).upper(), match.group(2).upper()))
    return ranges


def _numeric_bound_assertions(text: str) -> set[tuple[str, str, str]]:
    directions = {
        "至少": "minimum",
        "不少于": "minimum",
        "不低于": "minimum",
        "最短": "minimum",
        "最低": "minimum",
        "及以上": "minimum",
        "或以上": "minimum",
        "至多": "maximum",
        "不多于": "maximum",
        "不超过": "maximum",
        "最长": "maximum",
        "最高": "maximum",
        "及以下": "maximum",
        "或以下": "maximum",
    }
    assertions: set[tuple[str, str, str]] = set()
    for match in _MEDICAL_WRITING_NUMERIC_BOUND_RE.finditer(text):
        marker = match.group("prefix") or match.group("suffix")
        number = match.group("number") or match.group("number2")
        unit = match.group("unit") or match.group("unit2")
        assertions.add((directions[marker], number, "天" if unit == "日" else unit))
    for match in re.finditer(
        r"(?:最长|最多|不超过)[^。；;\n]{0,60}?"
        r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>天|日|周|月|年|小时)",
        text,
    ):
        assertions.add(
            (
                "maximum",
                match.group("number"),
                "天" if match.group("unit") == "日" else match.group("unit"),
            )
        )
    return assertions


def validate_medical_writing_revision_semantics(
    output: Dict[str, Any],
    allowed_sources: Iterable[Any],
) -> List[str]:
    """Reject AI-only upgrades of controlled protocol design labels."""
    sources = list(allowed_sources)
    fact_source_text = "\n".join(
        str(getattr(source, "text_preview", "") or "")
        for source in sources
        if getattr(source, "source_type", "")
        not in {
            "company_protocol_reference_corpus",
            "shared_phase1_protocol_reference_corpus",
        }
    )
    current_project_source_text = "\n".join(
        str(getattr(source, "text_preview", "") or "")
        for source in sources
        if getattr(source, "source_type", "")
        not in _MEDICAL_WRITING_REFERENCE_ONLY_SOURCE_TYPES
    )
    target_source_text = (
        str(getattr(sources[0], "text_preview", "") or "") if sources else ""
    )
    is_blank_greenfield_draft = bool(
        sources
        and getattr(sources[0], "source_type", "")
        == "greenfield_working_copy_selection"
        and not target_source_text.strip()
    )
    supported_labels = {
        label
        for label, patterns in _MEDICAL_WRITING_CONTROLLED_LABEL_PATTERNS.items()
        if any(
            re.search(
                pattern,
                target_source_text if label.startswith("status.") else fact_source_text,
            )
            for pattern in patterns
        )
    }
    population_source_text = (
        fact_source_text if is_blank_greenfield_draft else target_source_text
    )
    source_population_terms = {
        term
        for term in _MEDICAL_WRITING_POPULATION_TERMS
        if term in population_source_text
    }
    revision = output.get("revision")
    if not isinstance(revision, dict):
        return []
    candidates = [revision, *(revision.get("alternatives") or [])]
    errors: List[str] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        proposal_text = str(candidate.get("proposal_text") or "")
        candidate_labels = {
            label
            for label, patterns in _MEDICAL_WRITING_CONTROLLED_LABEL_PATTERNS.items()
            if any(re.search(pattern, proposal_text) for pattern in patterns)
        }
        unsupported = sorted(candidate_labels.difference(supported_labels))
        prefix = "revision" if index == 0 else f"revision.alternatives[{index - 1}]"
        if unsupported:
            errors.append(
                f"{prefix}.proposal_text introduces controlled protocol labels "
                f"not supported by current-project sources: {unsupported}"
            )
        omitted_required_labels = sorted(
            supported_labels.intersection(
                _MEDICAL_WRITING_REQUIRED_PRESERVATION_LABELS
            ).difference(candidate_labels)
        )
        if omitted_required_labels:
            errors.append(
                f"{prefix}.proposal_text omits required source timing labels: "
                f"{omitted_required_labels}"
            )
        region_specific_supported = bool(
            _MEDICAL_WRITING_NON_CHINA_REGION_PATTERN.search(
                current_project_source_text
            )
        )
        source_roman_ranges = _roman_level_ranges(
            fact_source_text,
            ignore_region_specific=(
                is_blank_greenfield_draft and not region_specific_supported
            ),
        )
        candidate_roman_ranges = _roman_level_ranges(proposal_text)
        missing_roman_ranges = sorted(
            source_roman_ranges.difference(candidate_roman_ranges)
        )
        introduced_roman_ranges = sorted(
            candidate_roman_ranges.difference(source_roman_ranges)
        )
        if missing_roman_ranges:
            errors.append(
                f"{prefix}.proposal_text omits source Roman-numeral level ranges: "
                f"{missing_roman_ranges}"
            )
        if introduced_roman_ranges:
            errors.append(
                f"{prefix}.proposal_text changes or invents Roman-numeral level ranges: "
                f"{introduced_roman_ranges}"
            )
        source_bounds = _numeric_bound_assertions(fact_source_text)
        candidate_bounds = _numeric_bound_assertions(proposal_text)
        reversed_bounds = sorted(
            candidate_bound
            for candidate_bound in candidate_bounds
            if (
                ("maximum" if candidate_bound[0] == "minimum" else "minimum"),
                candidate_bound[1],
                candidate_bound[2],
            )
            in source_bounds
        )
        if reversed_bounds:
            errors.append(
                f"{prefix}.proposal_text reverses numeric bound directions: "
                f"{reversed_bounds}"
            )
        if "重要的副作用" in fact_source_text and re.search(
            r"严重(?:的)?副作用", proposal_text
        ):
            errors.append(f"{prefix}.proposal_text upgrades 重要的副作用 to 严重副作用")
        if _MEDICAL_WRITING_EASI_IGA_EQUIVALENCE_RE.search(
            proposal_text
        ) and not _MEDICAL_WRITING_EASI_IGA_EQUIVALENCE_RE.search(
            current_project_source_text
        ):
            errors.append(
                f"{prefix}.proposal_text invents an EASI/IGA equivalence relation"
            )
        if _MEDICAL_WRITING_CONTRACEPTION_GROUPING_RE.search(proposal_text):
            errors.append(
                f"{prefix}.proposal_text incorrectly groups distinct contraception "
                "methods under abstinence"
            )
        if is_blank_greenfield_draft and not region_specific_supported:
            regional_terms = sorted(
                set(_MEDICAL_WRITING_NON_CHINA_REGION_PATTERN.findall(proposal_text))
            )
            if regional_terms:
                errors.append(
                    f"{prefix}.proposal_text introduces non-China regional clauses "
                    f"without current-project support: {regional_terms}"
                )
        project_population_facts = "\n".join(
            match
            for match in re.findall(
                r"(?:目标研究人群|研究人群概述)：([^\n]+)",
                current_project_source_text,
            )
        )
        if (
            "开发区域：中国" in current_project_source_text
            and "中国" not in project_population_facts
            and _MEDICAL_WRITING_CHINA_AS_POPULATION_ATTRIBUTE_RE.search(proposal_text)
        ):
            errors.append(
                f"{prefix}.proposal_text converts development region China into "
                "an unsupported participant nationality or population attribute"
            )
        project_references = set(
            _MEDICAL_WRITING_PROTOCOL_REFERENCE_RE.findall(current_project_source_text)
        )
        introduced_references = sorted(
            set(
                _MEDICAL_WRITING_PROTOCOL_REFERENCE_RE.findall(proposal_text)
            ).difference(project_references)
        )
        if introduced_references:
            errors.append(
                f"{prefix}.proposal_text introduces competitor protocol cross-references: "
                f"{introduced_references}"
            )
        candidate_population_terms = {
            term for term in _MEDICAL_WRITING_POPULATION_TERMS if term in proposal_text
        }
        introduced_population_terms = sorted(
            candidate_population_terms.difference(source_population_terms)
        )
        omitted_population_terms = (
            []
            if is_blank_greenfield_draft
            else sorted(source_population_terms.difference(candidate_population_terms))
        )
        if introduced_population_terms:
            errors.append(
                f"{prefix}.proposal_text introduces population terms not present "
                f"in current-project sources: {introduced_population_terms}"
            )
        if omitted_population_terms:
            errors.append(
                f"{prefix}.proposal_text omits controlled population terms from "
                f"current-project sources: {omitted_population_terms}"
            )
        if is_blank_greenfield_draft:
            placeholders = sorted(
                {
                    pattern
                    for pattern in _BLANK_DRAFT_PLACEHOLDER_PATTERNS
                    if re.search(pattern, proposal_text)
                }
            )
            if placeholders:
                errors.append(
                    f"{prefix}.proposal_text contains unresolved blank-draft placeholders: "
                    f"{placeholders}"
                )
    return errors


def bind_exact_source_quotes(
    task_type: AiTaskType,
    output: Dict[str, Any],
    allowed_sources: Iterable[Any],
) -> Dict[str, Any]:
    """Bind provenance quotes to registered text after the model selects a source."""
    if task_type not in EXACT_SOURCE_QUOTE_TASKS:
        return output
    source_by_id = {source.source_id: source for source in allowed_sources}
    evidence_spans = output.get("evidence_spans")
    if not isinstance(evidence_spans, list):
        return output
    bound_spans = []
    changed = False
    for item in evidence_spans:
        if not isinstance(item, dict):
            bound_spans.append(item)
            continue
        source = source_by_id.get(item.get("source_id"))
        if source is None or item.get("locator") != source.locator:
            bound_spans.append(item)
            continue
        bound = dict(item)
        if bound.get("quote") != source.text_preview and _quote_binding_equivalent(
            bound.get("quote"), source.text_preview
        ):
            bound["quote"] = source.text_preview
            changed = True
        bound_spans.append(bound)
    if not changed:
        return output
    normalized = dict(output)
    normalized["evidence_spans"] = bound_spans
    return normalized


def evidence_quote_matches_source(
    task_type: AiTaskType,
    source: Any,
    quote: str,
) -> bool:
    source_text = str(getattr(source, "text_preview", "") or "")
    if (
        task_type == AiTaskType.MEDICAL_WRITING_REVISION
        and getattr(source, "source_type", "")
        in MEDICAL_WRITING_BOUNDED_QUOTE_SOURCE_TYPES
    ):
        return bool(quote.strip()) and quote in source_text
    return quote == source_text


def _normalize_protocol_number_spacing(text: str) -> str:
    normalized = re.sub(r"(?<=\d)\s+(?=(?:周岁|岁|天|周|月|年))", "", text)
    normalized = re.sub(r"\s*%\s*", "%", normalized)
    normalized = re.sub(r"\s*[~～]\s*", "～", normalized)
    return normalized


def _protocol_condition_variants(source_text: str) -> list[str]:
    variants: list[str] = []

    def append(candidate: str) -> None:
        candidate = candidate.strip()
        if candidate and re.sub(r"\s+", "", candidate) not in {
            re.sub(r"\s+", "", item) for item in variants
        }:
            variants.append(candidate)

    append(source_text)
    append(_normalize_protocol_number_spacing(source_text))
    marker = "研究对象包括："
    if marker in source_text:
        prefix, tail = source_text.split(marker, 1)
        suffix = "。" if tail.endswith("。") else ""
        body = tail[:-1] if suffix else tail
        clauses = [item.strip() for item in body.split("，") if item.strip()]
        if len(clauses) >= 2:
            numbered = "；".join(
                f"{symbol}{clause}" for symbol, clause in zip("①②③④⑤⑥⑦⑧⑨", clauses)
            )
            append(f"{prefix}{marker}{numbered}{suffix}")
            append(f"{prefix}{marker}{'；'.join(clauses)}{suffix}")
    for index, character in enumerate(source_text):
        if character != "，":
            continue
        append(f"{source_text[:index]}；{source_text[index + 1 :]}")
    return variants


def normalize_single_source_medical_writing_candidates(
    task_type: AiTaskType,
    output: Dict[str, Any],
    allowed_sources: Iterable[Any],
    task_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Keep no-evidence candidate text useful without forcing the model to invent support."""
    if task_type != AiTaskType.MEDICAL_WRITING_REVISION:
        return output
    sources = list(allowed_sources)
    intent = task_context.get("revision_intent")
    if len(sources) != 1 or intent not in {"consistency_check", "evidence_gap"}:
        return output
    revision = output.get("revision")
    source_text = str(getattr(sources[0], "text_preview", "") or "").strip()
    candidate_count = task_context.get("candidate_count")
    if (
        not isinstance(revision, dict)
        or not source_text
        or not isinstance(candidate_count, int)
    ):
        return output
    variants = _protocol_condition_variants(source_text)
    if len(variants) < candidate_count:
        return output
    existing = [revision, *(revision.get("alternatives") or [])]
    base_evidence_ids = revision.get("evidence_span_ids")
    if not isinstance(base_evidence_ids, list) or not base_evidence_ids:
        return output
    strategy_labels = (
        "原文保留",
        "数字与标点最小规范",
        "既有条件序号化",
        "既有条件分号化",
    )
    normalized_candidates = []
    for index, proposal_text in enumerate(variants[:candidate_count]):
        original_candidate = (
            existing[index]
            if index < len(existing) and isinstance(existing[index], dict)
            else revision
        )
        ai_rationale = str(
            original_candidate.get("rationale") or revision.get("rationale") or ""
        ).strip()
        strategy = strategy_labels[index]
        normalized_candidates.append(
            {
                "proposal_text": proposal_text,
                "diff_patch": (
                    "无正文变更：保留原文"
                    if proposal_text == source_text
                    else f"- {source_text}\n+ {proposal_text}"
                ),
                "rationale": (
                    f"单来源安全变体（{strategy}）：当前没有外部证据，系统未增加医学事实或证据性表述。"
                    + (f" AI核查摘要：{ai_rationale}" if ai_rationale else "")
                ),
                "evidence_span_ids": list(
                    original_candidate.get("evidence_span_ids") or base_evidence_ids
                ),
                **(
                    {
                        "citation_bindings": deepcopy(
                            original_candidate.get("citation_bindings")
                        )
                    }
                    if "citation_bindings" in original_candidate
                    else {}
                ),
            }
        )
    normalized = dict(output)
    normalized_revision = dict(revision)
    normalized_revision.update(normalized_candidates[0])
    normalized_revision["alternatives"] = normalized_candidates[1:]
    normalized["revision"] = normalized_revision
    return normalized


def strip_blank_greenfield_anchor_evidence(
    task_type: AiTaskType,
    output: Dict[str, Any],
    allowed_sources: Iterable[Any],
) -> Dict[str, Any]:
    """Keep an empty greenfield editor anchor as context, never as evidence."""
    if task_type != AiTaskType.MEDICAL_WRITING_REVISION:
        return output
    blank_source_ids = {
        source.source_id
        for source in allowed_sources
        if source.source_type == "greenfield_working_copy_selection"
        and not str(source.text_preview or "").strip()
    }
    if not blank_source_ids:
        return output
    evidence_spans = output.get("evidence_spans")
    if not isinstance(evidence_spans, list):
        return output
    removed_span_ids = {
        item.get("span_id")
        for item in evidence_spans
        if isinstance(item, dict) and item.get("source_id") in blank_source_ids
    }
    removed_span_ids.discard(None)
    if not removed_span_ids:
        return output

    normalized = dict(output)
    normalized["evidence_spans"] = [
        item
        for item in evidence_spans
        if not (
            isinstance(item, dict) and item.get("source_id") in blank_source_ids
        )
    ]

    findings = output.get("findings")
    if isinstance(findings, list):
        retained_findings = []
        for finding in findings:
            if not isinstance(finding, dict):
                retained_findings.append(finding)
                continue
            evidence_ids = finding.get("evidence_span_ids")
            if not isinstance(evidence_ids, list):
                retained_findings.append(finding)
                continue
            retained_ids = [
                span_id
                for span_id in evidence_ids
                if span_id not in removed_span_ids
            ]
            if evidence_ids and not retained_ids:
                continue
            retained_finding = dict(finding)
            retained_finding["evidence_span_ids"] = retained_ids
            retained_findings.append(retained_finding)
        normalized["findings"] = retained_findings

    revision = output.get("revision")
    if isinstance(revision, dict):
        normalized_revision = dict(revision)
        evidence_ids = revision.get("evidence_span_ids")
        if isinstance(evidence_ids, list):
            normalized_revision["evidence_span_ids"] = [
                span_id
                for span_id in evidence_ids
                if span_id not in removed_span_ids
            ]
        alternatives = revision.get("alternatives")
        if isinstance(alternatives, list):
            normalized_alternatives = []
            for alternative in alternatives:
                if not isinstance(alternative, dict):
                    normalized_alternatives.append(alternative)
                    continue
                normalized_alternative = dict(alternative)
                alternative_ids = alternative.get("evidence_span_ids")
                if isinstance(alternative_ids, list):
                    normalized_alternative["evidence_span_ids"] = [
                        span_id
                        for span_id in alternative_ids
                        if span_id not in removed_span_ids
                    ]
                normalized_alternatives.append(normalized_alternative)
            normalized_revision["alternatives"] = normalized_alternatives
        normalized["revision"] = normalized_revision
    return normalized


def normalize_protocol_full_draft_evidence_ids(
    task_type: AiTaskType,
    output: Dict[str, Any],
    allowed_sources: Iterable[Any] = (),
) -> Dict[str, Any]:
    """Remove dangling section evidence IDs without accepting unsupported prose.

    If another valid span remains, only the dangling identity is removed.  If
    no valid span remains, the section is conservatively converted to an
    explicit source gap and its unsupported prose and decisions are discarded.
    """
    if task_type != AiTaskType.PROTOCOL_FULL_DRAFT:
        return output
    spans = output.get("evidence_spans")
    full_draft = output.get("full_draft")
    sections = full_draft.get("sections") if isinstance(full_draft, dict) else None
    if not isinstance(spans, list) or not isinstance(sections, list):
        return output
    source_by_id = {
        str(getattr(source, "source_id", "") or ""): source
        for source in allowed_sources
    }
    valid_spans = []
    for item in spans:
        if not isinstance(item, dict):
            continue
        source = source_by_id.get(str(item.get("source_id") or ""))
        quote = str(item.get("quote") or "")
        if source_by_id and (
            source is None
            or str(item.get("locator") or "") != str(getattr(source, "locator", "") or "")
            or not quote
            or quote not in str(getattr(source, "text_preview", "") or "")
        ):
            continue
        valid_spans.append(item)
    valid_ids = {
        item.get("span_id")
        for item in valid_spans
        if isinstance(item, dict)
        and isinstance(item.get("span_id"), str)
        and item.get("span_id")
    }
    changed = len(valid_spans) != len(spans)
    normalized_sections: list[Any] = []
    for section in sections:
        if not isinstance(section, dict):
            normalized_sections.append(section)
            continue
        evidence_ids = section.get("evidence_span_ids")
        if not isinstance(evidence_ids, list):
            normalized_sections.append(section)
            continue
        status = str(section.get("content_status") or "")
        retained = list(
            dict.fromkeys(item for item in evidence_ids if item in valid_ids)
        )
        force_source_gap = (
            status in {"complete", "partial"}
            and _FULL_DRAFT_UNSUPPORTED_RATIONALE_RE.search(
                str(section.get("rationale") or "")
            )
            and _FULL_DRAFT_UNSUPPORTED_SPECIFIC_RULE_RE.search(
                str(section.get("proposal_text") or "")
            )
        )
        force_neutral_decision = status == "decision_required"
        if (
            retained == evidence_ids
            and status != "source_gap"
            and not force_source_gap
            and not force_neutral_decision
        ):
            normalized_sections.append(section)
            continue
        changed = True
        normalized = dict(section)
        normalized["evidence_span_ids"] = retained
        if status == "source_gap" or force_source_gap:
            gap_items = list(normalized.get("gap_items") or [])
            if not gap_items:
                gap_items = [{
                    "gap_id": "gap:unsupported-evidence",
                    "category": "source_missing",
                    "target": str(normalized.get("section_id") or "本章节"),
                    "action": "补充或重新绑定能够直接支持本章节主张的当前项目来源。",
                    "missing_source_classes": list(
                        normalized.get("missing_source_classes")
                        or ["支持本章节研究实施规则的项目权威资料或职能确认"]
                    )[:4],
                }]
            normalized.update(
                {
                    "content_status": "source_gap",
                    "proposal_text": "",
                    "decision_items": [],
                    "evidence_span_ids": [],
                    "missing_source_classes": list(
                        normalized.get("missing_source_classes")
                        or ["支持本章节研究实施规则的项目权威资料或职能确认"]
                    )[:4],
                    "rationale": str(normalized.get("rationale") or "").strip()
                    or "现有项目资料不足以支持本章节正文。",
                    "gap_items": gap_items,
                }
            )
        elif not retained:
            normalized.update(
                {
                    "content_status": "source_gap",
                    "proposal_text": "",
                    "rationale": (
                        "本次输出未能把正文绑定到有效证据；需补充或重新绑定支持本章节的当前项目直接来源。"
                    ),
                    "decision_items": [],
                    "missing_source_classes": ["支持本章节正文的当前项目直接来源"],
                    "gap_items": [{
                        "gap_id": "gap:evidence-binding",
                        "category": "mapping_failed",
                        "target": str(normalized.get("section_id") or "本章节"),
                        "action": "恢复本章节正文与当前项目来源的证据绑定后重新核对。",
                        "missing_source_classes": [],
                    }],
                }
            )
        elif force_neutral_decision:
            normalized["proposal_text"] = ""
            normalized["missing_source_classes"] = []
            if not normalized.get("gap_items"):
                decisions = list(normalized.get("decision_items") or [])
                normalized["gap_items"] = [{
                    "gap_id": "gap:decision:" + hashlib.sha256(
                        str(item.get("question") or index).encode("utf-8")
                    ).hexdigest()[:20],
                    "category": "decision_pending",
                    "target": str(normalized.get("section_id") or "本章节"),
                    "action": str(item.get("question") or "确认本章节科学决定"),
                    "missing_source_classes": [],
                } for index, item in enumerate(decisions)]
        normalized_sections.append(normalized)
    if not changed:
        return output
    normalized_output = dict(output)
    normalized_full_draft = dict(full_draft)
    normalized_full_draft["sections"] = normalized_sections
    normalized_output["full_draft"] = normalized_full_draft
    normalized_findings: list[Any] = []
    for finding in output.get("findings") or []:
        if not isinstance(finding, dict):
            normalized_findings.append(finding)
            continue
        evidence_ids = finding.get("evidence_span_ids")
        if not isinstance(evidence_ids, list):
            normalized_findings.append(finding)
            continue
        retained = list(
            dict.fromkeys(item for item in evidence_ids if item in valid_ids)
        )
        if retained != evidence_ids:
            changed = True
            finding = dict(finding)
            finding["evidence_span_ids"] = retained
        normalized_findings.append(finding)
    normalized_output["findings"] = normalized_findings
    referenced_ids = {
        span_id
        for section in normalized_sections
        if isinstance(section, dict)
        for span_id in section.get("evidence_span_ids") or []
    }
    referenced_ids.update(
        span_id
        for finding in normalized_findings
        if isinstance(finding, dict)
        for span_id in finding.get("evidence_span_ids") or []
    )
    normalized_output["evidence_spans"] = [
        item for item in valid_spans if item.get("span_id") in referenced_ids
    ]
    return normalized_output


def bind_protocol_synopsis_source_quotes(
    task_type: AiTaskType,
    output: Dict[str, Any],
    allowed_sources: Iterable[Any],
) -> Dict[str, Any]:
    """Restore synopsis evidence to the exact source text after benign layout normalization."""
    if task_type != AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING:
        return output
    source_by_id = {source.source_id: source for source in allowed_sources}
    evidence_spans = output.get("evidence_spans")
    if not isinstance(evidence_spans, list):
        return output
    bound_spans = []
    changed = False
    for item in evidence_spans:
        if not isinstance(item, dict):
            bound_spans.append(item)
            continue
        source = source_by_id.get(item.get("source_id"))
        if source is None or item.get("locator") != source.locator:
            bound_spans.append(item)
            continue
        exact_quote = _source_substring_for_normalized_quote(
            item.get("quote"), source.text_preview
        )
        if exact_quote is None:
            # An unrelated or invented quote must remain visible to the strict
            # validator. Replacing it with the whole source paragraph would
            # falsely make any field that cites this span appear supported.
            bound_spans.append(item)
            continue
        if exact_quote == item.get("quote"):
            bound_spans.append(item)
            continue
        bound = dict(item)
        bound["quote"] = exact_quote
        bound_spans.append(bound)
        changed = True
    if not changed:
        return output
    normalized = dict(output)
    normalized["evidence_spans"] = bound_spans
    return normalized


_SYNOPSIS_OBJECTIVE_LABELS = {
    "主要目的": "primary",
    "次要目的": "secondary",
    "探索性目的": "exploratory",
}
_SYNOPSIS_ENDPOINT_LABELS = {
    "主要终点": "primary",
    "主要有效性终点": "primary",
    "关键次要终点": "key_secondary",
    "关键次要有效性终点": "key_secondary",
    "次要终点": "secondary",
    "次要有效性终点": "secondary",
    "其他终点": "secondary",
    "安全性终点": "safety",
    "探索性终点": "exploratory",
}
_SYNOPSIS_ANCHORED_FIELD_BY_CATEGORY = {
    "primary": "picos.primary_endpoint",
    "key_secondary": "picos.key_secondary_endpoints",
    "secondary": "picos.other_secondary_endpoints",
    "safety": "picos.safety_endpoints",
    "exploratory": "picos.exploratory_endpoints",
}
_SYNOPSIS_OBJECTIVE_FIELD_BY_CATEGORY = {
    "primary": "picos.primary_objectives",
    "secondary": "picos.secondary_objectives",
    "exploratory": "picos.exploratory_objectives",
}


def _synopsis_source_order_key(source: Any, fallback_index: int) -> tuple[int, int]:
    locator = str(getattr(source, "locator", "") or "")
    match = re.search(r":b(\d+)(?:$|[^0-9])", locator)
    if match:
        return int(match.group(1)), fallback_index
    return 1_000_000 + fallback_index, fallback_index


def _canonical_synopsis_clause(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"^\s*(?:[•·●○▪■]|\d+\s*[）).、])\s*", "", text)
    text = text.replace("**", "")
    text = re.sub(r"[\s，。；：、,.\uFF1B\uFF1A()（）\[\]【】{}“”‘’\"']+", "", text)
    return text.casefold()


def _clean_synopsis_source_item(value: str) -> str:
    value = value.strip().replace("**", "")
    return re.sub(r"^\s*(?:[•·●○▪■]|\d+\s*[）).、])\s*", "", value).strip()


def _split_synopsis_labeled_block(
    block: str,
    labels: Dict[str, str],
    *,
    default_category: str = "",
) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    category = default_category
    label_pattern = "|".join(sorted((re.escape(key) for key in labels), key=len, reverse=True))
    for raw_line in str(block or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(
            rf"^(?P<label>{label_pattern})(?:，包括但不限于)?\s*[:：]?\s*(?P<tail>.*)$",
            line,
        )
        if match:
            category = labels[match.group("label")]
            tail = _clean_synopsis_source_item(match.group("tail"))
            if tail:
                sections.setdefault(category, []).append(tail)
            continue
        if category:
            sections.setdefault(category, []).append(_clean_synopsis_source_item(line))
    return sections


def _protocol_synopsis_row_anchors(
    allowed_sources: Iterable[Any],
) -> Dict[str, List[tuple[str, str, str]]]:
    ordered_sources = sorted(
        enumerate(allowed_sources),
        key=lambda item: _synopsis_source_order_key(item[1], item[0]),
    )
    anchors: Dict[str, List[tuple[str, str, str]]] = {}
    pending_category = ""

    def append(field_path: str, text: str, source: Any) -> None:
        clean = _clean_synopsis_source_item(text)
        if not clean:
            return
        anchors.setdefault(field_path, []).append(
            (clean, str(source.source_id), str(source.locator))
        )

    for _, source in ordered_sources:
        source_text = str(getattr(source, "text_preview", "") or "")
        if not source_text.strip():
            continue
        cells = [cell.strip() for cell in source_text.split("\t") if cell.strip()]
        if not cells:
            continue

        first_label = re.sub(r"\s+", "", cells[0]).rstrip("：:")
        if first_label in {"研究目的", "试验目的"} and len(cells) >= 2:
            sections = _split_synopsis_labeled_block(
                "\n".join(cells[1:]), _SYNOPSIS_OBJECTIVE_LABELS
            )
            for category, items in sections.items():
                field_path = _SYNOPSIS_OBJECTIVE_FIELD_BY_CATEGORY.get(category)
                if not field_path:
                    continue
                for item in items:
                    append(field_path, item, source)
            pending_category = ""
            continue
        if first_label in {"研究终点", "试验终点", "疗效终点"} and len(cells) >= 2:
            sections = _split_synopsis_labeled_block(
                "\n".join(cells[1:]), _SYNOPSIS_ENDPOINT_LABELS
            )
            for category, items in sections.items():
                field_path = _SYNOPSIS_ANCHORED_FIELD_BY_CATEGORY[category]
                if category == "primary":
                    append(field_path, "\n".join(items), source)
                else:
                    for item in items:
                        append(field_path, item, source)
            pending_category = ""
            continue

        header_category = next(
            (
                category
                for cell in cells
                if (category := _SYNOPSIS_OBJECTIVE_LABELS.get(cell.rstrip("：:")))
            ),
            "",
        )
        if header_category and any("相应的研究终点" in cell for cell in cells):
            pending_category = header_category
            continue

        if pending_category and len(cells) >= 2:
            objective_cell, endpoint_cell = cells[-2], cells[-1]
            objective_field = _SYNOPSIS_OBJECTIVE_FIELD_BY_CATEGORY.get(
                pending_category
            )
            for item in (
                _clean_synopsis_source_item(line)
                for line in objective_cell.splitlines()
                if line.strip()
            ):
                if objective_field:
                    append(objective_field, item, source)
            sections = _split_synopsis_labeled_block(
                endpoint_cell,
                _SYNOPSIS_ENDPOINT_LABELS,
                default_category=pending_category,
            )
            for category, items in sections.items():
                field_path = _SYNOPSIS_ANCHORED_FIELD_BY_CATEGORY[category]
                if category == "primary":
                    append(field_path, "\n".join(items), source)
                else:
                    for item in items:
                        append(field_path, item, source)
            pending_category = ""
    return anchors


def _protocol_front_matter_anchors(
    allowed_sources: Iterable[Any],
) -> Dict[str, tuple[str, str, str]]:
    """Extract exact protocol identity facts from ordered front-matter rows."""

    ordered_sources = sorted(
        enumerate(allowed_sources),
        key=lambda item: _synopsis_source_order_key(item[1], item[0]),
    )
    anchors: Dict[str, tuple[str, str, str]] = {}
    label_fields = {
        "临床方案号": "framing.protocol_id",
        "方案编号": "framing.protocol_id",
        "方案号": "framing.protocol_id",
        "方案版本号": "framing.version",
        "方案版本": "framing.version",
        "研究题目": "framing.document_title",
        "试验题目": "framing.document_title",
        "方案标题": "framing.document_title",
        "研究分期": "framing.study_phase",
        "试验分期": "framing.study_phase",
        "试验药物名称": "framing.investigational_product",
        "研究药物名称": "framing.investigational_product",
        "试验药物": "framing.investigational_product",
        "研究药物": "framing.investigational_product",
        "适应症": "framing.indication",
    }
    title_candidate: tuple[str, str, str] | None = None

    def record(field_path: str, value: str, source: Any) -> None:
        clean = re.sub(r"\s+", " ", str(value or "")).strip(" \t:：")
        if not clean or field_path in anchors:
            return
        if field_path == "framing.version":
            version_match = re.fullmatch(
                r"[vV]?\s*(\d+(?:\.\d+)+)",
                clean,
            )
            if version_match:
                clean = f"V{version_match.group(1)}"
        anchors[field_path] = (
            clean,
            str(source.source_id),
            str(source.locator),
        )

    for source_index, (_, source) in enumerate(ordered_sources):
        if source_index >= 12:
            break
        source_text = str(getattr(source, "text_preview", "") or "").strip()
        if not source_text:
            continue
        cells = [
            re.sub(r"\s+", " ", cell).strip()
            for cell in re.split(r"[\t\r\n]+", source_text)
            if cell.strip()
        ]
        leading_labels: List[str] = []
        for cell in cells:
            label = re.sub(r"\s+", "", cell).rstrip("：:")
            if label not in label_fields:
                break
            leading_labels.append(label)
        if (
            len(leading_labels) >= 2
            and len(cells) >= len(leading_labels) * 2
        ):
            value_offset = len(leading_labels)
            for index, label in enumerate(leading_labels):
                record(label_fields[label], cells[value_offset + index], source)
        for index, cell in enumerate(cells[:-1]):
            label = re.sub(r"\s+", "", cell).rstrip("：:")
            field_path = label_fields.get(label)
            next_label = re.sub(r"\s+", "", cells[index + 1]).rstrip("：:")
            if field_path and next_label not in label_fields:
                record(field_path, cells[index + 1], source)
        for label, field_path in label_fields.items():
            match = re.search(
                rf"(?:^|[\t\r\n])\s*{re.escape(label)}\s*[：:]\s*([^\t\r\n]+)",
                source_text,
            )
            if match:
                record(field_path, match.group(1), source)
        compact = re.sub(r"\s+", " ", source_text).strip()
        if (
            title_candidate is None
            and 12 <= len(compact) <= 500
            and "研究" in compact
            and not compact.startswith("本研究")
            and not compact.endswith(("。", "；", ";"))
            and not any(token in compact for token in ("拟评价", "旨在", "研究目的"))
            and compact not in {"临床研究方案", "临床试验方案", "研究方案"}
            and not any(label in compact for label in label_fields)
        ):
            title_candidate = (
                compact,
                str(source.source_id),
                str(source.locator),
            )

    if "framing.document_title" not in anchors and title_candidate:
        anchors["framing.document_title"] = title_candidate
    return anchors


def _synopsis_field_value(study_definition: Dict[str, Any], field_path: str) -> Any:
    section_name, field_name = field_path.split(".", 1)
    section = study_definition.get(section_name)
    if not isinstance(section, dict):
        return None
    return section.get(field_name)


def validate_protocol_synopsis_source_fidelity(
    output: Dict[str, Any],
    allowed_sources: Iterable[Any],
) -> List[str]:
    """Reject source-synopsis fields that compress, merge, reorder, or lose source facts."""
    study_definition = output.get("study_definition")
    if not isinstance(study_definition, dict):
        return []
    sources = list(allowed_sources)
    evidence_by_id = {
        str(item.get("span_id")): item
        for item in output.get("evidence_spans", [])
        if isinstance(item, dict) and isinstance(item.get("span_id"), str)
    }
    field_evidence = study_definition.get("field_evidence_span_ids")
    field_evidence = field_evidence if isinstance(field_evidence, dict) else {}
    anchors = _protocol_synopsis_row_anchors(sources)
    errors: List[str] = []

    def mapped_source_ids(field_path: str) -> List[str]:
        result: List[str] = []
        for evidence_id in field_evidence.get(field_path, []):
            evidence = evidence_by_id.get(str(evidence_id))
            source_id = str(evidence.get("source_id")) if evidence else ""
            if source_id and source_id not in result:
                result.append(source_id)
        return result

    for field_path, expected_items in anchors.items():
        value = _synopsis_field_value(study_definition, field_path)
        actual_items = value if isinstance(value, list) else [value]
        actual_items = [str(item).strip() for item in actual_items if str(item or "").strip()]
        evidence_source_ids = set(mapped_source_ids(field_path))
        if len(actual_items) != len(expected_items):
            source_id = expected_items[min(len(actual_items), len(expected_items) - 1)][1]
            expected_ordered_text = " | ".join(
                f"{index + 1}. {text[:500]}"
                for index, (text, _, _) in enumerate(expected_items[:20])
            )
            errors.append(
                "protocol synopsis source fidelity error at "
                f"{field_path}: expected {len(expected_items)} ordered source item(s), got "
                f"{len(actual_items)}; synopsis source {source_id}; list items must remain "
                "one-to-one and must not be merged, omitted, or summarized; "
                f"expected ordered source items: {expected_ordered_text}"
            )
        for index, (expected_text, source_id, locator) in enumerate(expected_items):
            if index >= len(actual_items):
                break
            if _canonical_synopsis_clause(actual_items[index]) != _canonical_synopsis_clause(
                expected_text
            ):
                errors.append(
                    "protocol synopsis source fidelity error at "
                    f"{field_path}[{index}]: source clause was compressed, paraphrased, "
                    f"reordered, or lost qualifiers; synopsis source {source_id}; locator "
                    f"{locator}; expected source text: {expected_text}"
                )
            if source_id not in evidence_source_ids:
                errors.append(
                    "protocol synopsis source fidelity error at "
                    f"{field_path}[{index}]: source clause lacks field evidence mapping; "
                    f"synopsis source {source_id}; locator {locator}"
                )

    return errors


def build_required_field_hints(
    allowed_sources: Iterable[Any],
) -> Dict[str, int]:
    """Build a {field_path: expected_count} dict from deterministic anchors.

    This is injected into the synopsis-structuring prompt so the model knows
    exactly which anchored fields must be non-empty and how many items each
    must contain.
    """
    anchors = _protocol_synopsis_row_anchors(allowed_sources)
    return {field_path: len(items) for field_path, items in anchors.items()}


def materialize_anchored_synopsis_fields(
    output: Dict[str, Any],
    allowed_sources: Iterable[Any],
) -> Dict[str, Any]:
    """Deterministically restore anchored source items into the study
    definition when the model omits, paraphrases, reorders, or misbinds them.

    For every anchored field, materialize the exact ordered source items and
    their evidence bindings into the output. The model may supply
    semantic/unanchored fields, but it must not override, delete, reorder,
    compress, paraphrase, or detach exact anchored source items.

    This function runs before strict one-to-one validation.  It is the
    deterministic authority: even if the model drops an anchored field,
    the materialized result preserves exact source text and locators.
    """
    sources = list(allowed_sources)
    source_by_id = {str(source.source_id): source for source in sources}
    study_definition = output.get("study_definition")
    if not isinstance(study_definition, dict):
        return output
    anchors = _protocol_synopsis_row_anchors(sources)
    front_matter_anchors = _protocol_front_matter_anchors(sources)
    if not anchors and not front_matter_anchors:
        return output

    # Build evidence span lookup from model output.  Anchor identity includes
    # source and locator because the same wording can legitimately occur in
    # more than one source row.
    evidence_spans = output.get("evidence_spans", [])
    if not isinstance(evidence_spans, list):
        evidence_spans = []
    else:
        evidence_spans = list(evidence_spans)
    evidence_by_anchor: Dict[tuple[str, str, str], dict] = {}
    evidence_by_span_id: Dict[str, dict] = {}
    for span in evidence_spans:
        if isinstance(span, dict) and "quote" in span:
            span_id = str(span.get("span_id", ""))
            if span_id and span_id not in evidence_by_span_id:
                evidence_by_span_id[span_id] = span
            evidence_by_anchor[
                (
                    _canonical_synopsis_clause(span["quote"]),
                    str(span.get("source_id", "")),
                    str(span.get("locator", "")),
                )
            ] = span

    field_evidence = study_definition.get("field_evidence_span_ids")
    if not isinstance(field_evidence, dict):
        field_evidence = {}
    field_evidence = dict(field_evidence)

    changed = False
    study_definition = dict(study_definition)

    for field_path, expected_items in anchors.items():
        section_name, field_name = field_path.split(".", 1)
        section = study_definition.get(section_name)
        if not isinstance(section, dict):
            section = {}
        section = dict(section)
        value = section.get(field_name)
        actual_items = value if isinstance(value, list) else ([value] if value else [])
        actual_items = [str(item).strip() for item in actual_items if str(item or "").strip()]

        # Source rows are the deterministic authority for anchored fields.
        # Equal item counts are not sufficient: a model can still paraphrase,
        # reorder, or drop qualifiers in one item.
        materialized = [item[0] for item in expected_items]
        materialized_evidence_ids: List[str] = []
        for index, (expected_text, source_id, locator) in enumerate(expected_items):
            canonical = _canonical_synopsis_clause(expected_text)
            anchor_key = (canonical, source_id, locator)
            existing_span = evidence_by_anchor.get(anchor_key)
            if existing_span:
                span_id = str(existing_span.get("span_id", ""))
                if span_id:
                    materialized_evidence_ids.append(span_id)
            else:
                span_id = f"anchor_{field_path.replace('.', '_')}_{index}_{sha256(expected_text.encode('utf-8')).hexdigest()[:8]}"
                existing_named_span = evidence_by_span_id.get(span_id)
                if (
                    existing_named_span is not None
                    and str(existing_named_span.get("source_id", "")) == source_id
                    and str(existing_named_span.get("locator", "")) == locator
                ):
                    evidence_by_anchor[anchor_key] = existing_named_span
                else:
                    new_span = {
                        "span_id": span_id,
                        "source_id": source_id,
                        "locator": locator,
                        "quote": expected_text,
                    }
                    evidence_spans.append(new_span)
                    evidence_by_anchor[anchor_key] = new_span
                    evidence_by_span_id[span_id] = new_span
                    changed = True
                materialized_evidence_ids.append(span_id)

        materialized_value: Any
        if field_name == "primary_endpoint" and len(materialized) == 1:
            materialized_value = materialized[0]
        else:
            materialized_value = materialized
        if section.get(field_name) != materialized_value:
            section[field_name] = materialized_value
            changed = True

        exact_evidence_ids = list(dict.fromkeys(materialized_evidence_ids))
        if exact_evidence_ids and field_evidence.get(field_path) != exact_evidence_ids:
            field_evidence[field_path] = exact_evidence_ids
            changed = True

        study_definition[section_name] = section

    for field_path, (expected_text, source_id, locator) in front_matter_anchors.items():
        section_name, field_name = field_path.split(".", 1)
        section = study_definition.get(section_name)
        if not isinstance(section, dict):
            section = {}
        section = dict(section)
        if section.get(field_name) != expected_text:
            section[field_name] = expected_text
            changed = True

        anchor_key = (
            _canonical_synopsis_clause(expected_text),
            source_id,
            locator,
        )
        existing_span = evidence_by_anchor.get(anchor_key)
        if existing_span:
            span_id = str(existing_span.get("span_id", ""))
        else:
            span_id = (
                f"anchor_{field_path.replace('.', '_')}_"
                f"{sha256(expected_text.encode('utf-8')).hexdigest()[:8]}"
            )
            existing_named_span = evidence_by_span_id.get(span_id)
            if (
                existing_named_span is not None
                and str(existing_named_span.get("source_id", "")) == source_id
                and str(existing_named_span.get("locator", "")) == locator
            ):
                evidence_by_anchor[anchor_key] = existing_named_span
            else:
                new_span = {
                    "span_id": span_id,
                    "source_id": source_id,
                    "locator": locator,
                    "quote": (
                        str(source_by_id[source_id].text_preview)
                        if source_id in source_by_id
                        and _source_substring_for_normalized_quote(
                            expected_text,
                            str(source_by_id[source_id].text_preview),
                        )
                        is None
                        else expected_text
                    ),
                }
                evidence_spans.append(new_span)
                evidence_by_anchor[anchor_key] = new_span
                evidence_by_span_id[span_id] = new_span
                changed = True
        if span_id and field_evidence.get(field_path) != [span_id]:
            field_evidence[field_path] = [span_id]
            changed = True
        study_definition[section_name] = section

    framing = study_definition.get("framing")
    picos = study_definition.get("picos")
    if isinstance(framing, dict):
        version = str(framing.get("version") or "").strip()
        if (
            version == "V0.1"
            and "framing.version" not in front_matter_anchors
            and not field_evidence.get("framing.version")
        ):
            framing = dict(framing)
            framing["version"] = ""
            study_definition["framing"] = framing
            changed = True
    if isinstance(framing, dict) and isinstance(picos, dict):
        population_summary = str(picos.get("population_summary") or "").strip()
        if not str(framing.get("population_intent") or "").strip() and population_summary:
            framing = dict(framing)
            framing["population_intent"] = population_summary
            population_evidence = field_evidence.get("picos.population_summary")
            if population_evidence:
                field_evidence["framing.population_intent"] = list(population_evidence)
            study_definition["framing"] = framing
            changed = True

    if changed:
        study_definition["field_evidence_span_ids"] = field_evidence
        normalized = dict(output)
        normalized["study_definition"] = study_definition
        normalized["evidence_spans"] = evidence_spans
        return normalized
    return output


_PROTOCOL_SYNOPSIS_DESIGN_ENUM_ALIASES = {
    "randomization_mode": {
        "待定": "undecided",
        "未决定": "undecided",
        "尚未确定": "undecided",
        "随机": "randomized",
        "随机化": "randomized",
        "随机分配": "randomized",
        "非随机": "non_randomized",
        "非随机化": "non_randomized",
        "非随机分配": "non_randomized",
        "其他": "other",
    },
    "blinding_mode": {
        "待定": "undecided",
        "未决定": "undecided",
        "尚未确定": "undecided",
        "开放标签": "open_label",
        "开放性": "open_label",
        "开放": "open_label",
        "单盲": "single_blind",
        "双盲": "double_blind",
        "三盲": "triple_blind",
        "其他": "other",
    },
    "comparator_type": {
        "待定": "undecided",
        "未决定": "undecided",
        "尚未确定": "undecided",
        "安慰剂": "placebo",
        "安慰剂对照": "placebo",
        "阳性药": "active",
        "阳性对照": "active",
        "活性对照": "active",
        "无对照": "none_or_dose_escalation",
        "剂量递增": "none_or_dose_escalation",
        "无对照或剂量递增": "none_or_dose_escalation",
        "无对照/剂量递增": "none_or_dose_escalation",
        "其他": "other",
    },
}


def normalize_protocol_synopsis_design_enums(output: Dict[str, Any]) -> Dict[str, Any]:
    """Map exact, unambiguous Chinese display labels to contract enum values.

    The mapping is intentionally closed. Unknown or composite values remain
    unchanged so the nested contract validator continues to fail closed.
    """
    study_definition = output.get("study_definition")
    if not isinstance(study_definition, dict):
        return output
    framing = study_definition.get("framing")
    if not isinstance(framing, dict):
        return output
    structured_design = framing.get("structured_design")
    if not isinstance(structured_design, dict):
        return output

    normalized_design = dict(structured_design)
    changed = False
    for field_name, aliases in _PROTOCOL_SYNOPSIS_DESIGN_ENUM_ALIASES.items():
        raw_value = normalized_design.get(field_name)
        if not isinstance(raw_value, str):
            continue
        mapped = aliases.get(raw_value.strip())
        if mapped and mapped != raw_value:
            normalized_design[field_name] = mapped
            changed = True
    if not changed:
        return output

    normalized_framing = dict(framing)
    normalized_framing["structured_design"] = normalized_design
    normalized_study_definition = dict(study_definition)
    normalized_study_definition["framing"] = normalized_framing
    normalized = dict(output)
    normalized["study_definition"] = normalized_study_definition
    return normalized


def materialize_protocol_synopsis_structured_design(
    output: Dict[str, Any],
) -> Dict[str, Any]:
    """Project explicit source-backed synopsis wording into typed design fields.

    This is deliberately conservative. It only projects fields explicitly
    supported by source-bound framing/PICOS values. Those source facts outrank
    a conflicting model-supplied typed value. A comparison between dose groups
    of the same investigational product is represented as ``other`` rather than
    being mislabeled as placebo, active control, or dose escalation.
    """
    study_definition = output.get("study_definition")
    if not isinstance(study_definition, dict):
        return output
    framing = study_definition.get("framing")
    picos = study_definition.get("picos")
    if not isinstance(framing, dict) or not isinstance(picos, dict):
        return output
    structured_design = framing.get("structured_design")
    if not isinstance(structured_design, dict):
        return output

    field_evidence = study_definition.get("field_evidence_span_ids")
    if not isinstance(field_evidence, dict):
        field_evidence = {}
    field_evidence = {
        key: list(value) if isinstance(value, list) else value
        for key, value in field_evidence.items()
    }

    design_pattern = str(framing.get("design_pattern") or "").strip()
    comparator_summary = str(picos.get("comparator_summary") or "").strip()
    if not design_pattern:
        return output

    available_evidence_ids = {
        str(span.get("span_id"))
        for span in output.get("evidence_spans", [])
        if isinstance(span, dict) and str(span.get("span_id") or "")
    }
    evidence_text_by_id = {
        str(span.get("span_id")): str(
            span.get("quote") or span.get("source_text") or ""
        )
        for span in output.get("evidence_spans", [])
        if isinstance(span, dict) and str(span.get("span_id") or "")
    }
    design_evidence = field_evidence.get("framing.design_pattern")
    if not isinstance(design_evidence, list):
        return output
    design_evidence = [
        evidence_id
        for evidence_id in design_evidence
        if evidence_id in available_evidence_ids
    ]
    if not design_evidence:
        return output
    comparator_evidence = field_evidence.get("picos.comparator_summary")
    if not isinstance(comparator_evidence, list):
        comparator_evidence = []
    comparator_evidence = [
        evidence_id
        for evidence_id in comparator_evidence
        if evidence_id in available_evidence_ids
    ]
    design_support_text = "\n".join(
        [design_pattern]
        + [evidence_text_by_id.get(evidence_id, "") for evidence_id in design_evidence]
    )

    normalized_design = dict(structured_design)
    changed = False
    derived_evidence: Dict[str, List[str]] = {}

    def assign(
        field_name: str,
        value: Any,
        *,
        evidence_ids: List[str] | None = None,
    ) -> None:
        nonlocal changed
        if normalized_design.get(field_name) != value:
            normalized_design[field_name] = value
            changed = True
        derived_evidence[f"framing.structured_design.{field_name}"] = list(
            dict.fromkeys(evidence_ids or design_evidence)
        )

    # Prefer explicit negation before the positive token because "非随机"
    # contains "随机".
    if re.search(r"非随机(?:化|分配)?", design_support_text):
        assign("randomization_mode", "non_randomized")
    elif re.search(r"随机(?:化|分配)?", design_support_text):
        assign("randomization_mode", "randomized")

    blinding_match = (
        ("open_label", r"开放(?:标签|性)"),
        ("triple_blind", r"三盲"),
        ("double_blind", r"双盲"),
        ("single_blind", r"单盲"),
    )
    for value, pattern in blinding_match:
        if re.search(pattern, design_support_text):
            assign("blinding_mode", value)
            break

    if re.search(r"安慰剂(?:对照)?", design_support_text):
        assign(
            "comparator_type",
            "placebo",
            evidence_ids=design_evidence,
        )
    elif comparator_evidence and re.search(
        r"安慰剂(?:对照)?", comparator_summary
    ):
        assign(
            "comparator_type",
            "placebo",
            evidence_ids=comparator_evidence,
        )
    elif re.search(r"(?:阳性药|阳性对照|活性对照)", design_support_text):
        assign(
            "comparator_type",
            "active",
            evidence_ids=design_evidence,
        )
    elif comparator_evidence and re.search(
        r"(?:阳性药|阳性对照|活性对照)", comparator_summary
    ):
        assign(
            "comparator_type",
            "active",
            evidence_ids=comparator_evidence,
        )
    elif re.search(r"(?:单臂|无(?:平行)?对照|剂量递增)", design_support_text):
        assign("comparator_type", "none_or_dose_escalation")
    elif comparator_evidence and (
        re.search(r"(?:低|较低)剂量组", comparator_summary)
        and re.search(r"(?:高|较高)剂量组", comparator_summary)
    ):
        comparator_ids = list(dict.fromkeys(design_evidence + comparator_evidence))
        assign("comparator_type", "other", evidence_ids=comparator_ids)
        assign(
            "comparator_intervention",
            comparator_summary,
            evidence_ids=comparator_ids,
        )

    if re.search(r"(?:平行组?|平行对照)", design_support_text):
        assign("assignment_model", "平行组")
    elif re.search(r"交叉(?:设计|研究|试验)?", design_support_text):
        assign("assignment_model", "交叉设计")
    elif re.search(r"序贯", design_support_text):
        assign("assignment_model", "序贯设计")

    if re.search(r"多中心", design_support_text):
        assign("center_model", "多中心")
    elif re.search(r"单中心", design_support_text):
        assign("center_model", "单中心")

    if not changed:
        return output

    for field_path, evidence_ids in derived_evidence.items():
        if evidence_ids:
            field_evidence[field_path] = evidence_ids
    structured_ids: List[str] = []
    for field_path, evidence_ids in field_evidence.items():
        if (
            field_path.startswith("framing.structured_design.")
            and isinstance(evidence_ids, list)
        ):
            structured_ids.extend(evidence_ids)
    if structured_ids:
        field_evidence["framing.structured_design"] = list(
            dict.fromkeys(structured_ids)
        )

    normalized_framing = dict(framing)
    normalized_framing["structured_design"] = normalized_design
    normalized_study_definition = dict(study_definition)
    normalized_study_definition["framing"] = normalized_framing
    normalized_study_definition["field_evidence_span_ids"] = field_evidence
    normalized = dict(output)
    normalized["study_definition"] = normalized_study_definition
    return normalized



def normalize_protocol_synopsis_missing_findings(
    task_type: AiTaskType,
    output: Dict[str, Any],
) -> Dict[str, Any]:
    """Normalize source-free synopsis gaps without weakening non-default support checks."""
    if task_type != AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING:
        return output
    findings = output.get("findings")
    changed = False
    retained: list[Any] = []
    moved_descriptions: list[str] = []
    if isinstance(findings, list):
        for finding in findings:
            if (
                isinstance(finding, dict)
                and finding.get("status") == "insufficient_evidence"
                and finding.get("evidence_span_ids") == []
            ):
                title = finding.get("title")
                if isinstance(title, str) and title.strip():
                    moved_descriptions.append(title.strip())
                changed = True
                continue
            retained.append(finding)

    uncertainties = output.get("uncertainties")
    normalized_uncertainties = (
        list(uncertainties) if isinstance(uncertainties, list) else []
    )
    existing_descriptions = {
        item.get("description")
        for item in normalized_uncertainties
        if isinstance(item, dict)
    }
    for description in moved_descriptions:
        if description not in existing_descriptions:
            normalized_uncertainties.append(
                {"level": "data_gap", "description": description}
            )

    normalized_study_definition = output.get("study_definition")
    if isinstance(normalized_study_definition, dict):
        normalized_study_definition = dict(normalized_study_definition)
        field_evidence = normalized_study_definition.get("field_evidence_span_ids")
        if isinstance(field_evidence, dict):
            retained_field_evidence = {
                field_path: span_ids
                for field_path, span_ids in field_evidence.items()
                if span_ids != []
            }
            if len(retained_field_evidence) != len(field_evidence):
                normalized_study_definition["field_evidence_span_ids"] = (
                    retained_field_evidence
                )
                changed = True
                field_evidence = retained_field_evidence
        field_evidence = field_evidence if isinstance(field_evidence, dict) else {}
        picos = normalized_study_definition.get("picos")
        instruments = (
            picos.get("assessment_instruments") if isinstance(picos, dict) else None
        )
        if isinstance(instruments, list) and instruments:
            instrument_evidence_ids: list[str] = []
            all_items_source_bound = True
            for item in instruments:
                evidence_ids = (
                    item.get("evidence_span_ids") if isinstance(item, dict) else None
                )
                if not isinstance(evidence_ids, list) or not evidence_ids:
                    all_items_source_bound = False
                    break
                instrument_evidence_ids.extend(
                    span_id
                    for span_id in evidence_ids
                    if isinstance(span_id, str) and span_id.strip()
                )
            if all_items_source_bound and instrument_evidence_ids:
                existing_ids = field_evidence.get("picos.assessment_instruments")
                combined_ids = list(
                    dict.fromkeys(
                        [
                            *(existing_ids if isinstance(existing_ids, list) else []),
                            *instrument_evidence_ids,
                        ]
                    )
                )
                if existing_ids != combined_ids:
                    field_evidence = dict(field_evidence)
                    field_evidence["picos.assessment_instruments"] = combined_ids
                    normalized_study_definition["field_evidence_span_ids"] = (
                        field_evidence
                    )
                    changed = True
        missing_fields = [
            str(item)
            for item in normalized_study_definition.get("missing_fields", [])
            if isinstance(item, str) and item.strip()
        ]
        missing_set = set(missing_fields)
        for section_name, model_type in (
            ("framing", MedicalWritingStudyFraming),
            ("picos", MedicalWritingPicosDefinition),
        ):
            section = normalized_study_definition.get(section_name)
            if not isinstance(section, dict):
                continue
            section = dict(section)
            defaults = model_type().model_dump(mode="json")
            for field_name, default_value in defaults.items():
                if field_name not in section:
                    continue
                field_path = f"{section_name}.{field_name}"
                value = section[field_name]
                evidence_ids = field_evidence.get(field_path)
                has_evidence = isinstance(evidence_ids, list) and bool(evidence_ids)
                if value == default_value or (
                    has_evidence and field_path not in missing_set
                ):
                    continue
                section[field_name] = deepcopy(default_value)
                if field_path not in missing_set:
                    missing_fields.append(field_path)
                    missing_set.add(field_path)
                changed = True
            normalized_study_definition[section_name] = section
        if normalized_study_definition.get("missing_fields") != missing_fields:
            normalized_study_definition["missing_fields"] = missing_fields
            changed = True

    if not changed:
        return output
    normalized = dict(output)
    if isinstance(findings, list):
        normalized["findings"] = retained
        normalized["uncertainties"] = normalized_uncertainties
    if isinstance(normalized_study_definition, dict):
        normalized["study_definition"] = normalized_study_definition
    return normalized


_SYNOPSIS_PUNCTUATION_EQUIVALENTS = {
    "，": ",",
    "、": ",",
    "。": ".",
    "；": ";",
    "：": ":",
    "（": "(",
    "）": ")",
    "【": "[",
    "】": "]",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "－": "-",
    "–": "-",
    "—": "-",
}


def _source_substring_for_normalized_quote(candidate: Any, source: Any) -> str | None:
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    if not isinstance(source, str) or not source.strip():
        return None

    def canonicalize(value: str) -> tuple[str, list[int]]:
        canonical: list[str] = []
        source_indexes: list[int] = []
        for index, original in enumerate(value):
            for character in unicodedata.normalize("NFKC", original):
                if character.isspace():
                    continue
                canonical.append(
                    _SYNOPSIS_PUNCTUATION_EQUIVALENTS.get(character, character)
                )
                source_indexes.append(index)
        return "".join(canonical), source_indexes

    canonical_candidate, _ = canonicalize(candidate)
    canonical_source, source_indexes = canonicalize(source)
    if not canonical_candidate:
        return None
    offset = canonical_source.find(canonical_candidate)
    if offset < 0:
        return None
    start = source_indexes[offset]
    end = source_indexes[offset + len(canonical_candidate) - 1] + 1
    return source[start:end]


def _quote_binding_equivalent(candidate: Any, registered: Any) -> bool:
    if not isinstance(candidate, str) or not isinstance(registered, str):
        return False

    def fingerprint(value: str) -> str:
        compact = re.sub(r"\s+", " ", value.strip())
        return re.sub(r"[.。;；:：,，]+$", "", compact).strip()

    return bool(fingerprint(candidate)) and fingerprint(candidate) == fingerprint(
        registered
    )


class AiTaskStore:
    def __init__(self, jsonl_path: Path):
        self.jsonl_path = jsonl_path
        self._migrate_legacy_store()

    def append(self, run: AiTaskRun) -> None:
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with self.jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    audit_safe_ai_run(run).model_dump(mode="json"), ensure_ascii=False
                )
                + "\n"
            )

    def list_runs(self, project_id: str) -> List[AiTaskRun]:
        return [run for run in self._read_all() if run.project_id == project_id]

    def get(self, project_id: str, run_id: str) -> AiTaskRun:
        for run in self.list_runs(project_id):
            if run.run_id == run_id:
                return run
        raise KeyError(f"{project_id}/{run_id}")

    def artifacts(self, project_id: str, run_id: str) -> List[AiTaskArtifact]:
        return self.get(project_id, run_id).artifacts

    def _read_all(self) -> List[AiTaskRun]:
        if not self.jsonl_path.exists():
            return []
        runs: List[AiTaskRun] = []
        with self.jsonl_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                runs.append(AiTaskRun.model_validate(json.loads(line)))
        return runs

    def _migrate_legacy_store(self) -> None:
        if not self.jsonl_path.exists() or self.jsonl_path.stat().st_size == 0:
            return
        original_lines = self.jsonl_path.read_text(encoding="utf-8").splitlines()
        migrated_lines: List[str] = []
        changed = False
        for line_number, line in enumerate(original_lines, start=1):
            if not line.strip():
                continue
            try:
                original_payload = json.loads(line)
                run = AiTaskRun.model_validate(original_payload)
            except Exception as exc:
                raise ValueError(
                    f"invalid legacy AI run at line {line_number}: {exc}"
                ) from exc
            safe_payload = audit_safe_ai_run(run).model_dump(mode="json")
            migrated_lines.append(json.dumps(safe_payload, ensure_ascii=False))
            if safe_payload != original_payload:
                changed = True
        if not changed:
            return

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        backup_path = self.jsonl_path.with_name(
            f"{self.jsonl_path.name}.pre_audit_safe.{stamp}.bak"
        )
        backup_temp_path = self.jsonl_path.with_name(
            f".{self.jsonl_path.name}.{uuid4().hex}.backup.tmp"
        )
        temp_path = self.jsonl_path.with_name(
            f".{self.jsonl_path.name}.{uuid4().hex}.tmp"
        )
        try:
            with backup_temp_path.open("w", encoding="utf-8") as handle:
                if migrated_lines:
                    handle.write("\n".join(migrated_lines) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(backup_temp_path, backup_path)
            with temp_path.open("w", encoding="utf-8") as handle:
                if migrated_lines:
                    handle.write("\n".join(migrated_lines) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.jsonl_path)
        finally:
            if backup_temp_path.exists():
                backup_temp_path.unlink()
            if temp_path.exists():
                temp_path.unlink()


class AiTaskRunner:
    def __init__(
        self,
        repo: DemoRepository,
        store: AiTaskStore,
        provider_factory: Optional[
            Callable[[AiExecutionResolution], AiProvider]
        ] = None,
        prompt_registry: Optional[PromptRegistry] = None,
        policy_resolver: Optional[AiExecutionPolicyResolver] = None,
    ):
        self.repo = repo
        self.store = store
        self.provider_factory = provider_factory or _configured_provider_factory
        self.prompt_registry = prompt_registry or PromptRegistry()
        self.policy_resolver = policy_resolver or AiExecutionPolicyResolver()

    def submit(self, project_id: str, request: AiTaskRequest) -> AiTaskRun:
        raise AiExecutionPolicyDenied(
            "unresolved AI requests are not accepted; use registered or trusted server sources"
        )

    def submit_registered(self, project_id: str, request, source_registry) -> AiTaskRun:
        resolution = self.policy_resolver.resolve_registered(
            project_id,
            request,
            source_registry,
        )
        return self._execute(resolution)

    def submit_internal(self, project_id: str, request: AiTaskRequest) -> AiTaskRun:
        resolution = self.policy_resolver.resolve_internal(project_id, request)
        return self._execute(resolution)

    def _execute(self, resolution: AiExecutionResolution) -> AiTaskRun:
        project_id = resolution.project_id
        task_type = resolution.task_type
        run_id = f"airun_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)
        provider = self.provider_factory(resolution)
        _verify_provider_route_identity(provider, resolution)
        input_sources = list(resolution.allowed_sources)
        base = {
            "run_id": run_id,
            "project_id": project_id,
            "module": resolution.module,
            "task_type": task_type.value,
            "purpose": TASK_PURPOSES[task_type],
            "provider": resolution.provider_name,
            "model_name": resolution.model_name,
            "ai_gateway_status": "not_configured"
            if isinstance(provider, DisabledAiProvider)
            else "configured",
            "codex_runtime_dependency": False,
            "request_origin": resolution.request_origin,
            "data_classification": resolution.data_classification,
            "deployment_profile": resolution.deployment_profile,
            "policy_decision_id": resolution.policy_decision_id,
            "task_context_summary": dict(resolution.task_context),
            "prompt_version": resolution.prompt_version,
            "schema_version": "ai_task_output_v0_1",
            "input_sources": input_sources,
            "forbidden_source_ids": resolution.forbidden_source_ids,
            "route_profile_id": resolution.route_profile_id,
            "route_profile_revision": resolution.route_profile_revision,
            "route_transport": resolution.transport_name,
            "route_base_url": _audit_safe_base_url(resolution.base_url),
            "expected_response_model": resolution.required_response_model,
            "route_identity_hash": resolution.route_identity_hash,
            "created_at": now,
            "updated_at": now,
        }

        def normalize_provider_output(candidate: Dict[str, Any]) -> Dict[str, Any]:
            candidate = bind_exact_source_quotes(task_type, candidate, input_sources)
            candidate = bind_protocol_synopsis_source_quotes(
                task_type, candidate, input_sources
            )
            candidate = normalize_protocol_synopsis_missing_findings(
                task_type, candidate
            )
            if task_type == AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING:
                candidate = normalize_protocol_synopsis_design_enums(candidate)
                candidate = materialize_protocol_synopsis_structured_design(candidate)
                candidate = materialize_anchored_synopsis_fields(
                    candidate, input_sources
                )
                # Deterministic materialization may add identity evidence whose
                # normalized field value differs from the literal source
                # wording (for example source "1.3" -> field "V1.3"). Rebind
                # every newly added evidence quote to the exact source span
                # before strict validation.
                candidate = bind_protocol_synopsis_source_quotes(
                    task_type, candidate, input_sources
                )
            candidate = strip_blank_greenfield_anchor_evidence(
                task_type,
                candidate,
                input_sources,
            )
            candidate = normalize_protocol_full_draft_evidence_ids(
                task_type,
                candidate,
                input_sources,
            )
            return normalize_single_source_medical_writing_candidates(
                task_type,
                candidate,
                input_sources,
                dict(resolution.task_context),
            )

        try:
            spec = AiTaskSpec(
                task_id=run_id,
                task_type=task_type,
                prompt_version=resolution.prompt_version,
                allowed_sources=[
                    self._to_gateway_source(source) for source in input_sources
                ],
                forbidden_source_ids=resolution.forbidden_source_ids,
                user_instruction=resolution.user_instruction,
                provider_name=resolution.provider_name,
                model_name=resolution.model_name,
                task_context=dict(resolution.task_context),
            )
            envelope = self.prompt_registry.build(spec)
            if task_type == AiTaskType.PROTOCOL_FULL_DRAFT:
                # Full-draft batches ask a reasoning model for several
                # substantive sections plus evidence bindings in one JSON
                # object.  Provider defaults can spend the entire completion
                # budget on reasoning and return no final content, so this
                # task declares the same large bounded budget used by the
                # corpus-analysis workflow.
                envelope = AiPromptEnvelope(
                    task_id=envelope.task_id,
                    task_type=envelope.task_type,
                    prompt_version=envelope.prompt_version,
                    system_prompt=envelope.system_prompt,
                    payload=envelope.payload,
                    thinking=envelope.thinking,
                    reasoning_effort=envelope.reasoning_effort,
                    max_output_tokens=65_536,
                )
            if task_type == AiTaskType.MEDICAL_WRITING_REVISION:
                project_references = _project_references_from_store(
                    self.store, project_id
                )
                citation_payload = deepcopy(envelope.payload)
                citation_payload["project_citation_contract"] = {
                    "available_references": project_references,
                    "candidate_field": "citation_bindings",
                    "binding_item": {
                        "marker_text": "exact marker occurrence, for example [7]",
                        "display_numbers": "numbers parsed from that marker in source order; alignment only, never final numbering",
                        "reference_ids": "same-length ordered array of current-project reference_id values",
                    },
                    "rule": (
                        "Every numeric bracket citation in every proposal_text candidate must have one "
                        "citation_bindings item in occurrence order. If no current-project reference_id "
                        "supports a marker, remove the unsupported citation claim rather than returning a bare marker. "
                        "evidence_span_ids are evidence provenance and never substitute for reference_ids."
                    ),
                }
                envelope = AiPromptEnvelope(
                    task_id=envelope.task_id,
                    task_type=envelope.task_type,
                    prompt_version=envelope.prompt_version,
                    system_prompt=(
                        envelope.system_prompt
                        + "\n医学写作文献引文约束：proposal_text中的每个数字方括号引文必须按"
                        "payload.project_citation_contract返回citation_bindings；仅可使用其中列出的"
                        "当前项目reference_id。模型给出的数字只用于逐项对齐，不能作为最终显示编号。"
                        "evidence_span_ids与文献reference_id是不同身份，不得互相替代。"
                    ),
                    payload=citation_payload,
                    thinking=envelope.thinking,
                )
            provider_output = provider.run(envelope)
            _enforce_actual_response_model(provider, resolution)
            output = normalize_provider_output(provider_output)
        except AiGatewayConfigurationError as exc:
            run = AiTaskRun(
                **base,
                status=AiTaskRunStatus.BLOCKED,
                output_validation_status=AiTaskOutputValidationStatus.BLOCKED,
                error_message=str(exc),
                validation_errors=[str(exc)],
                actual_response_model=_provider_response_model(provider),
            )
            self.store.append(run)
            return run
        except AiProviderRuntimeError as exc:
            failure_artifacts = []
            if exc.diagnostics:
                failure_artifacts.append(
                    AiTaskArtifact(
                        artifact_id=f"artifact_{run_id}_provider_failure_diagnostics",
                        artifact_type="provider_failure_diagnostics",
                        payload={"diagnostics": dict(exc.diagnostics)},
                        validation_errors=[str(exc)],
                    )
                )
            run = AiTaskRun(
                **base,
                status=AiTaskRunStatus.FAILED,
                output_validation_status=AiTaskOutputValidationStatus.FAILED,
                error_message=str(exc),
                validation_errors=[str(exc)],
                actual_response_model=_provider_response_model(provider),
                artifacts=failure_artifacts,
            )
            self.store.append(run)
            return run

        validation_errors = self._validate_run_output(
            run_id,
            task_type,
            output,
            allowed_sources=input_sources,
            forbidden_source_ids=resolution.forbidden_source_ids,
            expected_provider=resolution.provider_name,
            expected_model=resolution.model_name,
            expected_prompt_version=resolution.prompt_version,
            expected_task_context=resolution.task_context,
        )
        attempt_artifacts: List[AiTaskArtifact] = []
        repairable_task_types = {
            AiTaskType.MEDICAL_WRITING_REVISION,
            AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING,
            AiTaskType.PROTOCOL_FULL_DRAFT,
        }
        if validation_errors and task_type in repairable_task_types:
            attempt_artifacts.append(
                AiTaskArtifact(
                    artifact_id=f"artifact_{run_id}_provider_output_attempt_1",
                    artifact_type="provider_output_attempt",
                    payload=output,
                    validation_errors=validation_errors,
                )
            )
            required_top_level_identity = {
                "task_id": run_id,
                "task_type": task_type.value,
                "provider": resolution.provider_name,
                "model": resolution.model_name,
                "prompt_version": resolution.prompt_version,
                "schema_version": "ai_task_output_v0_1",
                "input_source_ids": [source.source_id for source in input_sources],
                "forbidden_source_ids": list(resolution.forbidden_source_ids),
            }
            repair_context: Dict[str, Any] = {
                "instruction": (
                    "The previous provider output failed server validation. "
                    "Return one complete corrected JSON object for the original task. "
                    "Use only allowed_sources as evidence; the previous output is not evidence."
                ),
                "validation_errors": validation_errors,
                "previous_invalid_output": output,
                "required_top_level_identity": required_top_level_identity,
            }
            repair_system_prompt = (
                "\n上一次输出未通过服务器校验。请逐条修正payload.repair_context.validation_errors，"
                "重新返回完整JSON对象；必须逐字复制payload.repair_context.required_top_level_identity"
                "中的全部顶层身份字段，不得省略任何原任务字段，不得新增证据或改变原任务事实。"
            )
            if task_type == AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING:
                nested_contract_errors = [
                    error
                    for error in validation_errors
                    if error.startswith("protocol synopsis nested contract error")
                ]
                failed_source_ids = {
                    match.group(1)
                    for error in validation_errors
                    if (
                        match := re.search(
                            r"synopsis source ([^\s;]+)",
                            error,
                        )
                    )
                }
                repair_context["exact_source_quote_options"] = [
                    {
                        "source_id": source.source_id,
                        "locator": source.locator,
                        "text_preview": source.text_preview,
                    }
                    for source in input_sources
                    if source.source_id in failed_source_ids
                ]
                repair_context["instruction"] = (
                    "The previous synopsis extraction failed strict source validation. "
                    "For every listed source, copy source_id and locator exactly. If text_preview is "
                    "500 characters or fewer, copy the complete text_preview verbatim as quote. If it "
                    "is longer, use one unchanged continuous substring. Remove an evidence span and its "
                    "field mapping instead of inventing or paraphrasing evidence. For structured field "
                    "values, restore every source clause, qualifier, time point, population, dose/arm, "
                    "endpoint definition, and purpose/rationale. Keep source list items one-to-one and "
                    "ordered; do not merge or summarize them. Return the complete original task JSON and "
                    "do not change unsupported study facts."
                )
                field_hints = build_required_field_hints(input_sources)
                if field_hints:
                    repair_context["required_field_hints"] = field_hints
                    anchors = _protocol_synopsis_row_anchors(input_sources)
                    must_emit: List[Dict[str, Any]] = []
                    for field_path, items in anchors.items():
                        for index, (text, source_id, locator) in enumerate(items):
                            must_emit.append(
                                {
                                    "field_path": field_path,
                                    "index": index,
                                    "source_id": source_id,
                                    "locator": locator,
                                    "must_emit_verbatim": text,
                                }
                            )
                    if must_emit:
                        repair_context["must_emit_verbatim"] = must_emit
                        repair_context["instruction"] += (
                            " payload.repair_context.required_field_hints lists every "
                            "anchored field and its exact expected item count. "
                            "payload.repair_context.must_emit_verbatim lists the exact "
                            "source text that must appear in each anchored field; copy "
                            "each value verbatim into the corresponding field, preserving "
                            "order, punctuation, and all qualifiers. Do not leave any "
                            "field listed in required_field_hints empty or with fewer "
                            "items than the hint count."
                        )
                if nested_contract_errors:
                    instrument_contract = (
                        protocol_synopsis_assessment_instrument_contract()
                    )
                    repair_context["nested_contract"] = {
                        "validation_errors": nested_contract_errors,
                        "assessment_instrument_item_schema": instrument_contract,
                        "instrument_kind_enum": list(
                            PROTOCOL_SYNOPSIS_INSTRUMENT_KINDS
                        ),
                        "endpoint_paths_enum": list(
                            PROTOCOL_SYNOPSIS_INSTRUMENT_ENDPOINT_PATHS
                        ),
                        "endpoint_binding_semantics": instrument_contract[
                            "x_endpoint_binding_semantics"
                        ],
                    }
                    repair_context["instruction"] += (
                        " Correct every nested-contract error using repair_context.nested_contract. "
                        "Use the canonical enum values listed in the task contract. Preserve the complete picos. "
                        "prefix. Bind an ordinary secondary endpoint only to "
                        "picos.other_secondary_endpoints; use picos.key_secondary_endpoints only when "
                        "the source explicitly labels it key secondary. If the relationship is not "
                        "explicit, return endpoint_paths as an empty array."
                    )
                repair_system_prompt += (
                    "摘要证据修复时，payload.repair_context.exact_source_quote_options是本次失败来源的"
                    "逐字复制清单；500字以内必须把对应text_preview完整复制为quote。若不再采用该证据，"
                    "必须同时删除evidence span、引用它的field_evidence_span_ids映射以及量表候选中的"
                    "evidence_span_ids引用，不得改写或拼接原文。若失败项为source fidelity error，必须按"
                    "源表格行恢复全部事实从句、限定条件、时间点、人群、剂量/组别、终点定义和目的/依据；"
                    "列表逐项对应并保持原顺序，不得合并、概括或截短。"
                )
                if nested_contract_errors:
                    repair_system_prompt += (
                        "嵌套量表契约修复必须逐项遵守payload.repair_context.nested_contract中的"
                        "instrument_kind_enum、endpoint_paths_enum和层级语义；不得依赖服务端补全picos.前缀，"
                        "不得把普通次要终点升级为关键次要终点。关系未由原文明示时endpoint_paths返回空数组。"
                        "服务端不会静默删除或改写非法绑定；本次修复后仍非法将继续失败关闭。"
                    )
            if task_type == AiTaskType.PROTOCOL_FULL_DRAFT:
                failed_source_ids = {
                    match.group(1).rstrip(";,")
                    for error in validation_errors
                    if (
                        match := re.search(
                            r"allowed source ([^\s;]+)",
                            error,
                        )
                    )
                }
                if failed_source_ids:
                    repair_context["exact_source_quote_options"] = [
                        {
                            "source_id": source.source_id,
                            "locator": source.locator,
                            "text_preview": source.text_preview,
                        }
                        for source in input_sources
                        if source.source_id in failed_source_ids
                    ]
                repair_context["instruction"] = (
                    "The previous full-draft output failed strict section identity or substantive-content validation. "
                    "Return the complete original JSON object, preserving every requested section_id exactly once "
                    "and replacing every invalid or placeholder proposal_text with substantive Chinese protocol prose. "
                    "When exact_source_quote_options is present, every evidence quote must be copied character-for-character "
                    "as one unchanged continuous substring of the matching text_preview; remove the span and all references "
                    "to it instead of paraphrasing or inventing a quote."
                )
                repair_system_prompt += (
                    "全文初稿修复必须逐项覆盖payload.task_context.section_ids，保持原顺序和唯一身份；"
                    "每个proposal_text必须达到minimum_body_chars，不能是标题、Markdown表格、TBD/TODO、待补充、"
                    "不适用或‘由方案规定’等占位内容；不得把fixture、ProtocolAssemblyPlan、SECTION_ID、"
                    "evidence_span_ids等内部传输/测试标记写入正文，也不得保留‘待医学经理确认’、"
                    "‘尚待确认’、‘尚无直接证据支持’等未完成草稿指令；evidence_span_ids必须来自本次evidence_spans。"
                    "允许来源已经给出的年龄、剂量、频率、治疗周期、样本量、终点、量表和访视时间点必须直接写入正文；"
                    "不得使用‘将在正式文本中明确’、‘未提供具体数值’、‘由医学经理确认’或‘确认后再写入’等未来补写表达。"
                    "若repair_context提供exact_source_quote_options，证据quote必须从对应text_preview逐字复制连续原文；"
                    "不得改写、概括或拼接，无法逐字引用时应删除该证据及所有对它的引用。"
                )
            repair_payload = {
                **envelope.payload,
                "repair_context": repair_context,
            }
            repair_envelope = AiPromptEnvelope(
                task_id=envelope.task_id,
                task_type=envelope.task_type,
                prompt_version=envelope.prompt_version,
                system_prompt=envelope.system_prompt + repair_system_prompt,
                payload=repair_payload,
                thinking=envelope.thinking,
                reasoning_effort=envelope.reasoning_effort,
                max_output_tokens=envelope.max_output_tokens,
            )
            try:
                repaired_provider_output = provider.run(repair_envelope)
                _enforce_actual_response_model(provider, resolution)
                repaired_output = normalize_provider_output(repaired_provider_output)
                if task_type == AiTaskType.PROTOCOL_FULL_DRAFT:
                    # These fields are transport identity owned by the server,
                    # not generated medical content.  Some compatible JSON
                    # providers still omit one field during a corrective turn.
                    # Restore only missing values from the trusted request;
                    # an explicit mismatched value remains visible and fails
                    # the normal identity validation below.
                    for key, value in required_top_level_identity.items():
                        if key not in repaired_output:
                            repaired_output[key] = deepcopy(value)
                repaired_errors = self._validate_run_output(
                    run_id,
                    task_type,
                    repaired_output,
                    allowed_sources=input_sources,
                    forbidden_source_ids=resolution.forbidden_source_ids,
                    expected_provider=resolution.provider_name,
                    expected_model=resolution.model_name,
                    expected_prompt_version=resolution.prompt_version,
                    expected_task_context=resolution.task_context,
                )
                if repaired_errors and task_type == AiTaskType.PROTOCOL_FULL_DRAFT:
                    final_repair_context = {
                        **repair_context,
                        "instruction": (
                            "The first corrective response was still structurally invalid. This is the final bounded "
                            "same-model correction. Return exactly one complete top-level JSON object with findings, "
                            "evidence_spans, uncertainties, needs_medical_confirmation=true, and full_draft.sections. "
                            "full_draft.sections must contain every task_context.section_id exactly once and in order. "
                            "Do not return a bare section, finding, array, explanation, or Markdown. Preserve substantive "
                            "medical prose from the prior response only when it remains source-bound. Every evidence quote "
                            "must be an unchanged continuous substring of its matching allowed source."
                        ),
                        "validation_errors": repaired_errors,
                        "previous_invalid_output": repaired_output,
                        "repair_attempt": 2,
                    }
                    final_repair_envelope = AiPromptEnvelope(
                        task_id=envelope.task_id,
                        task_type=envelope.task_type,
                        prompt_version=envelope.prompt_version,
                        system_prompt=(
                            envelope.system_prompt
                            + repair_system_prompt
                            + "\n第一次纠错输出仍未通过结构校验。本次是最终一次同模型结构纠错；"
                            "必须返回唯一、完整的顶层JSON对象，不能返回裸章节、裸finding、数组、解释或Markdown。"
                        ),
                        payload={
                            **envelope.payload,
                            "repair_context": final_repair_context,
                        },
                        thinking=envelope.thinking,
                        reasoning_effort=envelope.reasoning_effort,
                        max_output_tokens=envelope.max_output_tokens,
                    )
                    final_provider_output = provider.run(final_repair_envelope)
                    _enforce_actual_response_model(provider, resolution)
                    final_output = normalize_provider_output(final_provider_output)
                    for key, value in required_top_level_identity.items():
                        if key not in final_output:
                            final_output[key] = deepcopy(value)
                    repaired_output = final_output
                    repaired_errors = self._validate_run_output(
                        run_id,
                        task_type,
                        repaired_output,
                        allowed_sources=input_sources,
                        forbidden_source_ids=resolution.forbidden_source_ids,
                        expected_provider=resolution.provider_name,
                        expected_model=resolution.model_name,
                        expected_prompt_version=resolution.prompt_version,
                        expected_task_context=resolution.task_context,
                    )
                output = repaired_output
                validation_errors = repaired_errors
            except (AiGatewayConfigurationError, AiProviderRuntimeError) as exc:
                validation_errors = [
                    *validation_errors,
                    f"{task_type.value} repair retry failed: {exc}",
                ]
        artifact = AiTaskArtifact(
            artifact_id=f"artifact_{run_id}_provider_output",
            artifact_type="provider_output",
            payload=output,
            validation_errors=validation_errors,
        )
        run = AiTaskRun(
            **base,
            status=AiTaskRunStatus.FAILED
            if validation_errors
            else AiTaskRunStatus.COMPLETED,
            output_validation_status=(
                AiTaskOutputValidationStatus.FAILED
                if validation_errors
                else AiTaskOutputValidationStatus.PASSED
            ),
            artifacts=[*attempt_artifacts, artifact],
            evidence_entries=self._evidence_entries(output),
            validation_errors=validation_errors,
            error_message="AI provider output failed validation"
            if validation_errors
            else "",
            needs_medical_confirmation=bool(
                output.get("needs_medical_confirmation", True)
            ),
            actual_response_model=_provider_response_model(provider),
        )
        self.store.append(run)
        return run

    def list_runs(self, project_id: str) -> List[AiTaskRun]:
        return self.store.list_runs(project_id)

    def get(self, project_id: str, run_id: str) -> AiTaskRun:
        return self.store.get(project_id, run_id)

    def artifacts(self, project_id: str, run_id: str) -> List[AiTaskArtifact]:
        return self.store.artifacts(project_id, run_id)

    def _validate_run_output(
        self,
        run_id: str,
        task_type: AiTaskType,
        output: Dict[str, Any],
        allowed_sources: List[Any],
        forbidden_source_ids: List[str],
        expected_provider: str,
        expected_model: str,
        expected_prompt_version: str,
        expected_task_context: Dict[str, Any],
    ) -> List[str]:
        errors = validate_ai_output(output)
        allowed_by_id = {source.source_id: source for source in allowed_sources}
        allowed_source_ids = list(allowed_by_id)
        if output.get("task_id") != run_id:
            errors.append(
                f"task_id mismatch: expected {run_id}, got {output.get('task_id')}"
            )
        if output.get("task_type") != task_type.value:
            errors.append(
                f"task_type mismatch: expected {task_type.value}, got {output.get('task_type')}"
            )
        if output.get("provider") != expected_provider:
            errors.append(
                f"provider mismatch: expected {expected_provider}, got {output.get('provider')}"
            )
        if output.get("model") != expected_model:
            errors.append(
                f"model mismatch: expected {expected_model}, got {output.get('model')}"
            )
        if output.get("prompt_version") != expected_prompt_version:
            errors.append(
                "prompt_version mismatch: "
                f"expected {expected_prompt_version}, got {output.get('prompt_version')}"
            )
        output_input_source_ids = output.get("input_source_ids")
        if isinstance(output_input_source_ids, list):
            expected_allowed = set(allowed_source_ids)
            actual_allowed = set(output_input_source_ids)
            unexpected = sorted(actual_allowed.difference(expected_allowed))
            missing = sorted(expected_allowed.difference(actual_allowed))
            if unexpected:
                errors.append(
                    f"provider returned unrequested input_source_ids: {unexpected}"
                )
            if missing:
                errors.append(f"provider omitted requested input_source_ids: {missing}")
        output_forbidden_source_ids = output.get("forbidden_source_ids")
        if isinstance(output_forbidden_source_ids, list):
            expected_forbidden = set(forbidden_source_ids)
            actual_forbidden = set(output_forbidden_source_ids)
            if actual_forbidden != expected_forbidden:
                errors.append(
                    "provider forbidden_source_ids mismatch: "
                    f"expected {sorted(expected_forbidden)}, got {sorted(actual_forbidden)}"
                )
        evidence_span_ids = set()
        for evidence in output.get("evidence_spans", []):
            if not isinstance(evidence, dict):
                continue
            span_id = evidence.get("span_id")
            if isinstance(span_id, str):
                if span_id in evidence_span_ids:
                    errors.append(f"duplicate evidence span_id: {span_id}")
                evidence_span_ids.add(span_id)
            source_id = evidence.get("source_id")
            if not isinstance(source_id, str) or source_id not in allowed_by_id:
                errors.append(
                    f"evidence span references unrequested source_id: {source_id}"
                )
                continue
            source = allowed_by_id[source_id]
            locator = evidence.get("locator")
            if locator != source.locator:
                errors.append(
                    f"evidence locator mismatch for {source_id}: expected {source.locator}, got {locator}"
                )
            quote = evidence.get("quote")
            if not isinstance(quote, str) or not quote.strip():
                errors.append(f"evidence quote is required for {source_id}")
            elif task_type in {
                AiTaskType.MEDICAL_WRITING_REVISION,
                AiTaskType.REGULATORY_TRANSLATION_ZH,
            }:
                if not evidence_quote_matches_source(task_type, source, quote):
                    errors.append(
                        f"evidence quote mismatch for exact writing source {source_id}"
                    )
            elif task_type == AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING:
                compact_quote = re.sub(r"\s+", " ", quote).strip()
                compact_source = re.sub(r"\s+", " ", source.text_preview).strip()
                if not compact_quote or compact_quote not in compact_source:
                    errors.append(
                        f"evidence quote is not present in synopsis source {source_id}"
                    )
            elif quote not in source.text_preview:
                errors.append(
                    f"evidence quote is not present in allowed source {source_id}"
                )

        for finding in output.get("findings", []):
            if not isinstance(finding, dict):
                continue
            source_id = finding.get("source_id")
            if not isinstance(source_id, str) or source_id not in allowed_by_id:
                errors.append(f"finding references unrequested source_id: {source_id}")
        if task_type == AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING:
            study_definition = output.get("study_definition")
            if isinstance(study_definition, dict):
                errors.extend(
                    self._validate_protocol_synopsis_nested_contract(study_definition)
                )
                errors.extend(
                    validate_protocol_synopsis_source_fidelity(
                        output,
                        allowed_sources,
                    )
                )
        if task_type == AiTaskType.MEDICAL_WRITING_REVISION:
            errors.extend(
                validate_medical_writing_revision_semantics(
                    output,
                    allowed_sources,
                )
            )
            project_id = next(
                (
                    str(source.project_id)
                    for source in allowed_sources
                    if str(getattr(source, "project_id", "")).strip()
                ),
                "",
            )
            errors.extend(
                validate_medical_writing_candidate_citations(
                    output,
                    _project_reference_ids_from_store(self.store, project_id),
                )
            )
        if task_type == AiTaskType.PROTOCOL_FULL_DRAFT:
            errors.extend(
                self._validate_protocol_full_draft_output(
                    output,
                    allowed_sources,
                    expected_task_context,
                )
            )
        if task_type == AiTaskType.ELIGIBILITY_RULE_REVIEW:
            errors.extend(
                self._validate_eligibility_batch_output(
                    output,
                    expected_task_context,
                )
            )
        if task_type == AiTaskType.REGULATORY_TRANSLATION_ZH:
            translation = output.get("translation")
            if isinstance(translation, dict):
                expected_glossary = expected_task_context.get("glossary_version")
                if translation.get("glossary_version") != expected_glossary:
                    errors.append(
                        "regulatory translation glossary_version mismatch: "
                        f"expected {expected_glossary}, got {translation.get('glossary_version')}"
                    )
                source_text = "\n".join(
                    str(source.text_preview or "") for source in allowed_sources
                )
                generated_text = "\n".join(
                    str(translation.get(key) or "")
                    for key in ("translated_text", "rationale")
                )
                for authority in REGULATORY_AUTHORITY_TERMS:
                    if re.search(
                        rf"(?<![A-Za-z]){re.escape(authority)}(?![A-Za-z])",
                        generated_text,
                        re.IGNORECASE,
                    ) and not re.search(
                        rf"(?<![A-Za-z]){re.escape(authority)}(?![A-Za-z])",
                        source_text,
                        re.IGNORECASE,
                    ):
                        errors.append(
                            "regulatory translation cites unrequested external authority: "
                            f"{authority}"
                        )
        return errors

    def _validate_protocol_full_draft_output(
        self,
        output: Dict[str, Any],
        allowed_sources: List[Any],
        context: Dict[str, Any],
    ) -> List[str]:
        errors: List[str] = []
        expected_ids = list(context.get("section_ids") or [])
        full_draft = output.get("full_draft")
        sections = full_draft.get("sections") if isinstance(full_draft, dict) else None
        if not isinstance(sections, list):
            return ["protocol_full_draft.full_draft.sections must be a list"]
        actual_ids = [
            item.get("section_id")
            for item in sections
            if isinstance(item, dict)
        ]
        if actual_ids != expected_ids:
            errors.append(
                "protocol full-draft section identity/order mismatch: "
                f"expected {expected_ids}, got {actual_ids}"
            )
        if len(actual_ids) != len(set(actual_ids)):
            errors.append("protocol full-draft section_id values must be unique")
        minimum = int(context.get("minimum_body_chars") or 0)
        evidence_ids = {
            str(item.get("span_id"))
            for item in output.get("evidence_spans", [])
            if isinstance(item, dict) and str(item.get("span_id") or "").strip()
        }
        source_text = "\n".join(
            str(getattr(source, "text_preview", "") or "") for source in allowed_sources
        )
        decision_fact_paths = set(context.get("decision_fact_paths") or [])
        for index, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            prefix = f"full_draft.sections[{index}]"
            section_id = str(section.get("section_id") or "")
            content_status = str(section.get("content_status") or "")
            if section_id not in expected_ids:
                errors.append(f"{prefix}.section_id is not in the requested section set")
            proposal = str(section.get("proposal_text") or "").strip()
            if content_status in {"complete", "partial"} and len(proposal) < minimum:
                errors.append(
                    f"{prefix}.proposal_text is not substantive: {len(proposal)} < {minimum} characters"
                )
            if _FULL_DRAFT_PLACEHOLDER_RE.search(proposal):
                errors.append(f"{prefix}.proposal_text contains a blank-draft placeholder")
            leaked_tokens = sorted(
                {
                    pattern.pattern
                    for pattern in _FULL_DRAFT_INTERNAL_TOKEN_PATTERNS
                    if pattern.search(proposal)
                }
            )
            if leaked_tokens:
                errors.append(
                    f"{prefix}.proposal_text contains internal transport/test vocabulary: "
                    + ", ".join(leaked_tokens)
                )
            unresolved_markers = sorted(
                {match.group() for match in iter_unresolved_draft_markers(proposal)}
            )
            if unresolved_markers:
                errors.append(
                    f"{prefix}.proposal_text contains unresolved drafting markers: "
                    + ", ".join(unresolved_markers)
                )
            drafting_process_markers = sorted(
                {match.group() for match in DRAFTING_PROCESS_VOCABULARY_RE.finditer(proposal)}
            )
            if drafting_process_markers:
                errors.append(
                    f"{prefix}.proposal_text contains drafting-process language: "
                    + ", ".join(drafting_process_markers)
                )
            if _FULL_DRAFT_HEADING_RE.fullmatch(proposal):
                errors.append(f"{prefix}.proposal_text contains only a heading")
            if re.search(r"^\s*\|.*\|\s*$", proposal, re.MULTILINE) and re.search(
                r"^\s*\|?\s*:?-{3,}", proposal, re.MULTILINE
            ):
                errors.append(f"{prefix}.proposal_text contains a Markdown table")
            candidate_evidence = section.get("evidence_span_ids")
            if not proposal and candidate_evidence:
                errors.append(f"{prefix}.evidence_span_ids must be empty for source_gap")
            elif proposal and (
                not isinstance(candidate_evidence, list) or not candidate_evidence
            ):
                errors.append(f"{prefix}.evidence_span_ids must be non-empty")
            elif isinstance(candidate_evidence, list) and any(
                span_id not in evidence_ids for span_id in candidate_evidence
            ):
                errors.append(f"{prefix}.evidence_span_ids references an unknown evidence span")
            rationale = str(section.get("rationale") or "")
            for decision_index, decision in enumerate(section.get("decision_items") or []):
                if not isinstance(decision, dict):
                    continue
                fact_path = str(decision.get("fact_path") or "")
                if fact_path not in decision_fact_paths:
                    errors.append(
                        f"{prefix}.decision_items[{decision_index}].fact_path is not an allowed study-definition path"
                    )
            if (
                content_status in {"complete", "partial"}
                and _FULL_DRAFT_UNSUPPORTED_RATIONALE_RE.search(rationale)
                and _FULL_DRAFT_UNSUPPORTED_SPECIFIC_RULE_RE.search(proposal)
            ):
                errors.append(
                    f"{prefix} writes an unsupported high-impact rule as complete; "
                    "return decision_required with choices instead"
                )
            if proposal and source_text and proposal == source_text.strip():
                errors.append(f"{prefix}.proposal_text must be section-specific, not the entire source packet")
        if output.get("needs_medical_confirmation") is not True:
            errors.append("protocol full-draft output requires medical confirmation")
        return errors

    def _validate_protocol_synopsis_nested_contract(
        self,
        study_definition: Dict[str, Any],
    ) -> List[str]:
        errors: List[str] = []
        field_evidence = study_definition.get("field_evidence_span_ids")
        field_evidence = field_evidence if isinstance(field_evidence, dict) else {}
        missing_fields = set(study_definition.get("missing_fields") or [])
        for field_name, model_type in (
            ("framing", MedicalWritingStudyFraming),
            ("picos", MedicalWritingPicosDefinition),
        ):
            payload = study_definition.get(field_name)
            if not isinstance(payload, dict):
                continue
            try:
                validated = model_type.model_validate(payload)
            except ValidationError as exc:
                for detail in exc.errors(include_input=False, include_url=False):
                    location = ".".join(str(item) for item in detail.get("loc", ()))
                    suffix = f".{location}" if location else ""
                    errors.append(
                        "protocol synopsis nested contract error at "
                        f"{field_name}{suffix}: {detail.get('msg', 'invalid value')}"
                    )
                continue
            if field_name == "picos":
                for index, instrument in enumerate(
                    validated.assessment_instruments
                ):
                    purpose = instrument.study_purpose
                    if (
                        "picos.key_secondary_endpoints"
                        in instrument.endpoint_paths
                        and "次要" in purpose
                        and "关键" not in purpose
                    ):
                        errors.append(
                            "protocol synopsis nested contract error at "
                            f"picos.assessment_instruments.{index}.endpoint_paths: "
                            "ordinary secondary endpoint must bind to "
                            "picos.other_secondary_endpoints and must not be upgraded "
                            "to picos.key_secondary_endpoints"
                        )
            defaults = model_type().model_dump(mode="json")
            values = validated.model_dump(mode="json")
            for nested_field, value in values.items():
                field_path = f"{field_name}.{nested_field}"
                if value == defaults.get(nested_field) or field_path in missing_fields:
                    continue
                evidence_ids = field_evidence.get(field_path)
                if not isinstance(evidence_ids, list) or not evidence_ids:
                    errors.append(
                        "protocol synopsis non-default value requires source evidence at "
                        f"{field_path}"
                    )
        return errors

    def _validate_eligibility_batch_output(
        self,
        output: Dict[str, Any],
        context: Dict[str, Any],
    ) -> List[str]:
        errors: List[str] = []
        for key in (
            "batch_id",
            "criterion_kind",
            "rule_revision",
            "subject_source_revision",
            "packet_digest",
        ):
            if output.get(key) != context.get(key):
                errors.append(
                    f"eligibility {key} mismatch: expected {context.get(key)}, "
                    f"got {output.get(key)}"
                )
        results = output.get("criterion_results")
        if not isinstance(results, list):
            return errors
        actual_uids = [
            result.get("criterion_uid")
            for result in results
            if isinstance(result, dict)
        ]
        expected_uids = list(context.get("criterion_uids") or [])
        if len(actual_uids) != len(set(actual_uids)):
            errors.append(
                "eligibility criterion_results contain duplicate criterion_uid"
            )
        missing = sorted(set(expected_uids).difference(actual_uids))
        unexpected = sorted(set(actual_uids).difference(expected_uids))
        if missing:
            errors.append(
                f"eligibility criterion_results omitted criterion_uids: {missing}"
            )
        if unexpected:
            errors.append(
                f"eligibility criterion_results contain unexpected criterion_uids: {unexpected}"
            )
        if len(actual_uids) != len(expected_uids):
            errors.append(
                "eligibility criterion_results count does not match the trusted batch"
            )
        allowed_evidence = set(context.get("allowed_evidence_ids") or [])
        for result in results:
            if not isinstance(result, dict):
                continue
            for evidence_id in result.get("evidence_ids") or []:
                if evidence_id not in allowed_evidence:
                    errors.append(
                        "eligibility criterion_result references unknown evidence_id: "
                        f"{evidence_id}"
                    )
        return errors

    def _evidence_entries(self, output: Dict[str, Any]) -> List[AiTaskEvidenceEntry]:
        finding_ids_by_span = self._finding_ids_by_span(output.get("findings", []))
        entries: List[AiTaskEvidenceEntry] = []
        for span in output.get("evidence_spans", []):
            if not isinstance(span, dict) or not isinstance(span.get("span_id"), str):
                continue
            entries.append(
                AiTaskEvidenceEntry(
                    evidence_id=span["span_id"],
                    source_id=str(span.get("source_id", "")),
                    locator=str(span.get("locator", "")),
                    quote=str(span.get("quote", "")),
                    finding_ids=finding_ids_by_span.get(span["span_id"], []),
                )
            )
        return entries

    def _finding_ids_by_span(self, findings: Iterable[Any]) -> Dict[str, List[str]]:
        mapping: Dict[str, List[str]] = {}
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            finding_id = finding.get("finding_id")
            for span_id in finding.get("evidence_span_ids", []):
                if isinstance(finding_id, str) and isinstance(span_id, str):
                    mapping.setdefault(span_id, []).append(finding_id)
        return mapping

    def _to_gateway_source(self, source: Any) -> AiSourceRef:
        return AiSourceRef(
            source_id=source.source_id,
            source_type=source.source_type,
            title=source.title,
            locator=source.locator,
            text_preview=source.text_preview,
        )


def audit_safe_ai_run(run: AiTaskRun) -> AiTaskRun:
    safe_sources = [
        source.model_copy(
            update={
                "title": _redact_runtime_text(source.title),
                "locator": _redact_runtime_text(source.locator),
                "text_preview": "",
            }
        )
        for source in run.input_sources
    ]
    safe_evidence = [
        entry.model_copy(
            update={
                "locator": _redact_runtime_text(entry.locator),
                "quote": "",
            }
        )
        for entry in run.evidence_entries
    ]
    safe_artifacts = []
    for artifact in run.artifacts:
        payload = artifact.payload if isinstance(artifact.payload, dict) else {}
        if SAFE_ARTIFACT_KEYS.issubset(payload) and set(payload).issubset(
            SAFE_ARTIFACT_KEYS | SAFE_ARTIFACT_OPTIONAL_KEYS
        ):
            safe_payload = dict(payload)
        else:
            payload_json = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, default=str
            )
            safe_payload = {
                "output_hash": sha256(payload_json.encode("utf-8")).hexdigest(),
                "top_level_keys": sorted(payload.keys()),
                "finding_count": len(payload.get("findings", []))
                if isinstance(payload.get("findings"), list)
                else 0,
                "evidence_span_count": len(payload.get("evidence_spans", []))
                if isinstance(payload.get("evidence_spans"), list)
                else 0,
            }
            if run.task_type == AiTaskType.MEDICAL_WRITING_REVISION.value:
                revision = payload.get("revision")
                candidates = []
                if isinstance(revision, dict):
                    candidates.append(revision)
                    alternatives = revision.get("alternatives")
                    if isinstance(alternatives, list):
                        candidates.extend(alternatives)
                binding_index = []
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    proposal_text = candidate.get("proposal_text")
                    bindings = candidate.get("citation_bindings")
                    if not isinstance(proposal_text, str) or not isinstance(
                        bindings, list
                    ):
                        continue
                    binding_index.append(
                        {
                            "proposal_sha256": sha256(
                                proposal_text.encode("utf-8")
                            ).hexdigest(),
                            "citation_bindings": deepcopy(bindings),
                        }
                    )
                if binding_index:
                    safe_payload["candidate_citation_bindings"] = binding_index
        safe_artifacts.append(
            artifact.model_copy(
                update={
                    "payload": safe_payload,
                    "validation_errors": [
                        _redact_runtime_text(value)
                        for value in artifact.validation_errors
                    ],
                }
            )
        )
    return run.model_copy(
        update={
            "input_sources": safe_sources,
            "artifacts": safe_artifacts,
            "evidence_entries": safe_evidence,
            "validation_errors": [
                _redact_runtime_text(value) for value in run.validation_errors
            ],
            "error_message": _redact_runtime_text(run.error_message),
        }
    )


def public_ai_run(run: AiTaskRun) -> Dict[str, Any]:
    payload = audit_safe_ai_run(run).model_dump(mode="json")
    for source in payload.get("input_sources", []):
        source.pop("text_preview", None)
    for evidence in payload.get("evidence_entries", []):
        evidence.pop("quote", None)
    return payload


def public_ai_artifacts(artifacts: List[AiTaskArtifact]) -> List[Dict[str, Any]]:
    synthetic_run = AiTaskRun(
        run_id="public_projection",
        project_id="public_projection",
        module="public_projection",
        task_type="public_projection",
        purpose="public_projection",
        status=AiTaskRunStatus.COMPLETED,
        provider="public_projection",
        model_name="public_projection",
        ai_gateway_status="public_projection",
        prompt_version="public_projection",
        artifacts=artifacts,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return [
        item.model_dump(mode="json")
        for item in audit_safe_ai_run(synthetic_run).artifacts
    ]


def _redact_runtime_text(value: str) -> str:
    return LOCAL_PATH_RE.sub("[local_path_redacted]", value or "")


def _verify_provider_route_identity(
    provider: AiProvider,
    resolution: AiExecutionResolution,
) -> None:
    """Fail closed when the created provider is not the frozen route.

    ``provider_name``/``model_name`` are mandatory protocol attributes and are
    always compared. Route attributes that a provider exposes (transport,
    base URL, expected response model) must equal the frozen resolution
    exactly; a provider that does not expose an attribute (for example an
    injected test double) is verified only on the attributes it does expose.
    Production providers built by the default factory expose the full
    identity, so any drift there is denied before the provider can run.
    """
    if provider.provider_name != resolution.provider_name:
        raise AiExecutionPolicyDenied(
            "resolved provider configuration mismatch: "
            f"expected {resolution.provider_name}, got {provider.provider_name}"
        )
    if provider.model_name != resolution.model_name:
        raise AiExecutionPolicyDenied(
            "resolved model configuration mismatch: "
            f"expected {resolution.model_name}, got {provider.model_name}"
        )
    exposed_checks = (
        ("transport_name", "transport", resolution.transport_name),
        ("base_url", "base URL", resolution.base_url),
        (
            "expected_response_model",
            "expected response model",
            resolution.required_response_model,
        ),
    )
    for attribute, label, expected in exposed_checks:
        actual = getattr(provider, attribute, None)
        if actual is None:
            continue
        if str(actual) != expected:
            raise AiExecutionPolicyDenied(
                f"resolved {label} configuration mismatch: "
                f"expected {expected}, got {actual}"
            )


def _provider_response_model(provider: AiProvider) -> str:
    return str(getattr(provider, "response_model", "") or "").strip()


def _enforce_actual_response_model(
    provider: AiProvider,
    resolution: AiExecutionResolution,
) -> None:
    """Fail closed when the provider's actual response model left the route.

    Production OpenAI-compatible providers verify the response identity
    inside ``run`` and raise before this point; this second check covers any
    provider that exposes a verified response model without enforcing it.
    Providers that expose no response model (injected test doubles, disabled
    or CLI providers) have nothing comparable and are skipped.
    """
    expected = resolution.required_response_model.strip()
    if not expected:
        return
    actual = _provider_response_model(provider)
    if not actual:
        return
    if actual != expected:
        raise AiProviderRuntimeError(
            "AI provider response model does not match the frozen route: "
            f"expected {expected}, got {actual}"
        )


def _audit_safe_base_url(value: str) -> str:
    """Strip URL userinfo so a credential-bearing base URL is never persisted."""
    text = (value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return text
    if not parsed.username and not parsed.password:
        return text
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


def _configured_provider_factory(resolution: AiExecutionResolution) -> AiProvider:
    """Build the default provider exclusively from the frozen resolution.

    No second dynamic route lookup happens here: provider, model, transport,
    base URL, expected response model and timeout all come from the route
    identity frozen at policy resolution, so a dynamic route mutation after
    resolution cannot alter the constructed provider. Only the API credential
    is resolved, keyed by the frozen profile id; a credential is not route
    identity and can never change provider, model, endpoint or transport.
    """
    values = dict(os.environ)
    if resolution.route_profile_id:
        api_key = runtime_ai_settings_store().credentials.get(
            resolution.route_profile_id
        )
        if api_key:
            values["WORKBENCH_AI_API_KEY"] = api_key
            if resolution.route_api_key_env:
                values[resolution.route_api_key_env] = api_key
    values.update(
        {
            "WORKBENCH_AI_PROVIDER": resolution.provider_name,
            "WORKBENCH_AI_TRANSPORT": resolution.transport_name,
            "WORKBENCH_AI_BASE_URL": resolution.base_url,
            "WORKBENCH_AI_MODEL": resolution.model_name,
            "WORKBENCH_AI_DEPLOYMENT_PROFILE": resolution.deployment_profile,
            "WORKBENCH_AI_TIMEOUT_SECONDS": str(resolution.route_timeout_seconds),
            "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": resolution.required_response_model,
        }
    )
    # The route identity is frozen above; role-level thinking options are
    # copied only when the binding still points at that exact frozen profile.
    # This keeps a late settings mutation from changing provider/model
    # identity while allowing the configured LLM thinking policy to reach the
    # request envelope.
    try:
        role_store = runtime_ai_role_settings_store()
        binding = role_store.binding(INDEPENDENT_AI_ROLE)
        if (
            binding.profile_id == resolution.route_profile_id
            and binding.model == resolution.model_name
        ):
            values.update(
                {
                    "WORKBENCH_AI_ROLE": INDEPENDENT_AI_ROLE,
                    "WORKBENCH_AI_THINKING": binding.thinking,
                    "WORKBENCH_AI_REASONING_EFFORT": binding.reasoning_effort,
                }
            )
    except (KeyError, ValueError):
        pass
    return configured_ai_provider_from_env(values)
