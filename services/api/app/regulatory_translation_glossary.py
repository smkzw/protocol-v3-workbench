from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


GLOSSARY_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "medical_writing_glossary"
    / "regulatory_translation_glossary_v1.json"
)

# Preferred Chinese labels for common protocol abbreviations.  These are
# prompt-side terminology hints, not permission to invent an abbreviation:
# callers must pass only abbreviations that are present in the source unit.
PREFERRED_CLINICAL_ABBREVIATION_TRANSLATIONS: dict[str, str] = {
    "AD": "特应性皮炎",
    "ADA": "抗药抗体",
    "ADSD": "特应性皮炎症状日记",
    "AE": "不良事件",
    "AEs": "不良事件",
    "BSA": "体表面积",
    "CRF": "病例报告表",
    "DLQI": "皮肤病生活质量指数",
    "EASI": "湿疹面积和严重程度指数",
    "EQ-5D-5L": "欧洲五维健康量表五级版本",
    "HADS": "医院焦虑抑郁量表",
    "IGA": "研究者整体评估",
    "IUD": "宫内节育器",
    "IUS": "宫内节育系统",
    "IV": "静脉",
    "MD": "医学博士",
    "MS": "理学硕士",
    "PD": "药效动力学",
    "PK": "药代动力学",
    "POEM": "患者导向型湿疹评估量表",
    "PRO": "患者报告结局",
    "SCORAD": "特应性皮炎评分",
    "SAE": "严重不良事件",
    "SAEs": "严重不良事件",
    "TEAE": "治疗期间出现的不良事件",
    "TEAEs": "治疗期间出现的不良事件",
    "VAS": "视觉模拟量表",
    "vIGA-AD": "经验证的特应性皮炎研究者整体评估量表",
    "WPAI-SHP": "特定健康问题所致工作生产力与活动受损量表",
}

_SUBJECT_PARTICIPANT_SOURCE_RE = re.compile(
    r"\b(?:subjects?|participants?)\b",
    re.IGNORECASE,
)
_PATIENT_SOURCE_RE = re.compile(r"\bpatients?\b", re.IGNORECASE)
_PATIENT_QUALIFIER_SOURCE_RE = re.compile(
    r"\bpatients?[-\s]+(?:reported|oriented)\b",
    re.IGNORECASE,
)
_SOURCE_PERSON_TERM_RE = re.compile(
    r"\b(?P<term>subjects?|participants?|patients?)\b",
    re.IGNORECASE,
)
_PROTECTED_PATIENT_TARGET_TERMS = (
    "患者报告结局",
    "患者导向型湿疹评估量表",
    "患者导向的湿疹评估量表",
)
_PROTECTED_PATIENT_TARGET_RE = re.compile(
    r"患者(?:"
    r"报告(?:的)?(?:结局|结果|量表|指标|评分|工具)"
    r"|导向(?:型|的)?[\u3400-\u9fffA-Za-z0-9-]{0,20}?(?:量表|评分|评估)"
    r")"
)
_TARGET_PERSON_TERM_RE = re.compile(r"受试者|患者")
_ELIDED_PARTICIPANT_SUFFIX_RE = re.compile(
    r"(?P<predicate>呈(?:阳性|阴性))者"
    r"(?=(?:需|应|须|可|将|不得|必须|接受|排除|入组|参加))"
)
_ELIDED_PARTICIPANT_PRONOUN_RE = re.compile(
    r"(?P<prefix>若|如|当)其"
    r"(?=(?:体内|血清|检查|检测|结果|病史|用药|症状|安全性|能力|水平))"
)


def source_has_patient_referent(source_text: str) -> bool:
    """Return whether ``patient`` denotes a person rather than a named measure."""
    without_named_measures = _PATIENT_QUALIFIER_SOURCE_RE.sub("", source_text or "")
    return bool(_PATIENT_SOURCE_RE.search(without_named_measures))


def source_person_term_sequence(source_text: str) -> tuple[str, ...]:
    """Return ordered person-denoting source terms, excluding named measures."""
    without_named_measures = _PATIENT_QUALIFIER_SOURCE_RE.sub("", source_text or "")
    sequence: list[str] = []
    for match in _SOURCE_PERSON_TERM_RE.finditer(without_named_measures):
        term = match.group("term").lower()
        sequence.append("patient" if term.startswith("patient") else "participant")
    return tuple(sequence)


def _protect_patient_measure_terms(target_text: str) -> tuple[str, dict[str, str]]:
    protected = target_text or ""
    placeholders: dict[str, str] = {}
    terms = list(_PROTECTED_PATIENT_TARGET_TERMS)
    terms.extend(match.group(0) for match in _PROTECTED_PATIENT_TARGET_RE.finditer(protected))
    for index, term in enumerate(dict.fromkeys(sorted(terms, key=len, reverse=True))):
        placeholder = f"__CMS_PATIENT_MEASURE_{index}__"
        if term in protected:
            protected = protected.replace(term, placeholder)
            placeholders[placeholder] = term
    return protected, placeholders


def _restore_patient_measure_terms(
    target_text: str,
    placeholders: dict[str, str],
) -> str:
    restored = target_text
    for placeholder, term in placeholders.items():
        restored = restored.replace(placeholder, term)
    return restored


def target_person_term_sequence(target_text: str) -> tuple[str, ...]:
    """Return ordered Chinese person terms after masking named measures."""
    protected, _ = _protect_patient_measure_terms(target_text)
    return tuple(
        "participant" if match.group(0) == "受试者" else "patient"
        for match in _TARGET_PERSON_TERM_RE.finditer(protected)
    )


def normalize_subject_participant_terminology(
    source_text: str,
    target_text: str,
) -> str:
    """Normalize a narrow Hy-MT2 participant-term drift deterministically.

    The normalization is applied only when the source contains
    ``subject/participant`` and has no person-denoting ``patient``.  Established
    measure names such as ``患者报告结局`` remain untouched.
    """
    source_sequence = source_person_term_sequence(source_text)
    if "participant" not in source_sequence:
        return target_text
    if "patient" in source_sequence:
        return target_text
    protected, placeholders = _protect_patient_measure_terms(target_text)
    normalized = protected.replace("患者", "受试者")
    required_mentions = source_sequence.count("participant")
    explicit_mentions = normalized.count("受试者")
    missing_mentions = max(0, required_mentions - explicit_mentions)
    if missing_mentions:
        normalized, replaced = _ELIDED_PARTICIPANT_SUFFIX_RE.subn(
            r"\g<predicate>的受试者",
            normalized,
            count=missing_mentions,
        )
        missing_mentions -= replaced
    if missing_mentions:
        normalized, _ = _ELIDED_PARTICIPANT_PRONOUN_RE.subn(
            r"\g<prefix>受试者",
            normalized,
            count=missing_mentions,
        )
    return _restore_patient_measure_terms(normalized, placeholders)


def participant_terminology_mismatch(
    source_text: str,
    target_text: str,
) -> bool:
    """Return whether a subject/participant source is rendered as ``患者``."""
    source_sequence = source_person_term_sequence(source_text)
    if "participant" not in source_sequence:
        return False
    target_sequence = target_person_term_sequence(target_text)
    if "patient" not in source_sequence:
        return "patient" in target_sequence
    return source_sequence != target_sequence


@lru_cache(maxsize=1)
def load_regulatory_translation_glossary() -> dict[str, Any]:
    payload = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "cms_regulatory_translation_glossary_v1":
        raise ValueError("unsupported regulatory translation glossary schema")
    ids = [entry.get("id") for entry in payload.get("entries", [])]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("regulatory translation glossary has missing or duplicate entry ids")
    source_ids = {
        source.get("source_id") for source in payload.get("source_registry", [])
    }
    if None in source_ids or len(source_ids) != len(payload.get("source_registry", [])):
        raise ValueError("regulatory translation glossary has invalid source registry")
    governance = payload.get("governance") or {}
    if not governance.get("authority_priority") or not governance.get("conflict_rules"):
        raise ValueError("regulatory translation glossary governance is incomplete")
    for entry in payload.get("entries", []):
        required = {"id", "english", "chinese", "domain", "locked", "source_refs"}
        if not required.issubset(entry) or not entry["source_refs"]:
            raise ValueError(f"regulatory translation glossary entry is incomplete: {entry.get('id')}")
        unknown_sources = set(entry["source_refs"]) - source_ids
        if unknown_sources:
            raise ValueError(
                f"regulatory translation glossary entry {entry['id']} has unknown sources: "
                f"{sorted(unknown_sources)}"
            )
    return payload


def regulatory_translation_glossary_hash() -> str:
    payload = load_regulatory_translation_glossary()
    canonical = json.dumps(
        {
            "glossary": payload,
            "preferred_clinical_abbreviation_translations": (
                PREFERRED_CLINICAL_ABBREVIATION_TRANSLATIONS
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _phrase_pattern(phrase: str) -> re.Pattern[str] | None:
    phrase = phrase.strip()
    if not phrase:
        return None
    phrase_pattern = r"\s+".join(re.escape(part) for part in re.split(r"\s+", phrase))
    return re.compile(
        rf"(?<![A-Za-z0-9]){phrase_pattern}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = _phrase_pattern(phrase)
    return bool(pattern and pattern.search(text))


def _phrase_spans(text: str, phrase: str) -> list[tuple[int, int]]:
    pattern = _phrase_pattern(phrase)
    return [match.span() for match in pattern.finditer(text)] if pattern else []


def select_regulatory_translation_terms(
    source_text: str,
    *,
    project_overrides: dict[str, str] | None = None,
    max_terms: int = 80,
) -> list[dict[str, Any]]:
    glossary = load_regulatory_translation_glossary()
    selected: list[dict[str, Any]] = []
    overrides = project_overrides or {}
    for entry in glossary["entries"]:
        phrases = [entry["english"], *entry.get("aliases", [])]
        matched = [phrase for phrase in phrases if _contains_phrase(source_text, phrase)]
        if not matched:
            continue
        if any(_contains_phrase(source_text, phrase) for phrase in entry.get("context_none", [])):
            continue
        required_context = entry.get("context_any", [])
        if required_context and not any(
            _contains_phrase(source_text, phrase) for phrase in required_context
        ):
            continue
        resolved = dict(entry)
        resolved["matched_phrases"] = sorted(matched, key=len, reverse=True)
        resolved["_matched_spans"] = sorted(
            {
                span
                for phrase in matched
                for span in _phrase_spans(source_text, phrase)
            }
        )
        if entry["id"] in overrides:
            resolved["base_chinese"] = entry["chinese"]
            resolved["chinese"] = overrides[entry["id"]]
            resolved["project_override"] = True
        selected.append(resolved)
    selected.sort(
        key=lambda item: (-max(len(x) for x in item["matched_phrases"]), item["id"])
    )
    retained: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for item in selected:
        spans = item.pop("_matched_spans")
        if spans and all(
            any(start >= used_start and end <= used_end for used_start, used_end in occupied)
            for start, end in spans
        ):
            continue
        retained.append(item)
        occupied.extend(spans)
        if len(retained) >= max_terms:
            break
    return retained


def render_regulatory_translation_glossary_contract(
    source_text: str,
    *,
    project_overrides: dict[str, str] | None = None,
) -> str:
    selected = select_regulatory_translation_terms(
        source_text,
        project_overrides=project_overrides,
    )
    if not selected:
        return ""
    glossary = load_regulatory_translation_glossary()
    lines = [f"本片段命中的受控术语（版本 {glossary['glossary_version']}）："]
    for entry in selected:
        lines.append(f"- english: {entry['english']}")
        lines.append(f"  preferred_zh: {entry['chinese']}")
        if entry.get("preserve_abbreviation") and _contains_phrase(
            source_text, entry["preserve_abbreviation"]
        ):
            lines.append(
                f"  preserve_source_abbreviation: {entry['preserve_abbreviation']}"
            )
        if entry.get("forbidden_chinese"):
            lines.append(
                "  forbidden_zh: " + "、".join(entry["forbidden_chinese"])
            )
        if entry.get("project_override"):
            lines.append(f"  project_override_base_zh: {entry['base_chinese']}")
    lines.append("不得对未命中的普通词作机械全局替换；上下文冲突时标记需医学确认，不得擅自改义。")
    return "\n".join(lines)


def render_preferred_abbreviation_contract(
    source_abbreviations: list[str] | tuple[str, ...],
) -> str:
    """Render preferred Chinese labels only for abbreviations in the source."""
    matched = [
        (abbreviation, PREFERRED_CLINICAL_ABBREVIATION_TRANSLATIONS[abbreviation])
        for abbreviation in source_abbreviations
        if abbreviation in PREFERRED_CLINICAL_ABBREVIATION_TRANSLATIONS
    ]
    if not matched:
        return ""
    lines = ["本单元缩写优选中文："]
    for abbreviation, preferred_zh in matched:
        lines.append(f"- abbreviation: {abbreviation}")
        lines.append(f"  preferred_zh: {preferred_zh}")
    return "\n".join(lines)


def evaluate_controlled_term_fidelity(source_text: str, translated_text: str) -> tuple[str, ...]:
    failures: list[str] = []
    for entry in select_regulatory_translation_terms(source_text):
        accepted = [entry["chinese"], *entry.get("accepted_chinese", [])]
        preserve_abbreviation = entry.get("preserve_abbreviation")
        expanded_source_terms = [
            term
            for term in [entry.get("english", ""), *entry.get("aliases", [])]
            if term and term.casefold() != str(preserve_abbreviation).casefold()
        ]
        if (
            preserve_abbreviation
            and _contains_phrase(source_text, preserve_abbreviation)
            and not any(
                _contains_phrase(source_text, term)
                for term in expanded_source_terms
            )
        ):
            accepted.append(preserve_abbreviation)
        if entry.get("locked") and not any(term in translated_text for term in accepted):
            failures.append(f"controlled_term_missing:{entry['id']}")
        forbidden_target = translated_text
        if entry["id"] == "participant":
            if source_has_patient_referent(source_text):
                forbidden_target = ""
            else:
                forbidden_target, _ = _protect_patient_measure_terms(translated_text)
        if any(term in forbidden_target for term in entry.get("forbidden_chinese", [])):
            failures.append(f"controlled_term_forbidden:{entry['id']}")
    return tuple(dict.fromkeys(failures))
