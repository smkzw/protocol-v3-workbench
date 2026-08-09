"""Resolve Chinese indication labels to ClinicalTrials.gov-compatible English terms.

ClinicalTrials.gov ``query.cond`` expects English/MeSH-style condition strings.
When ``framing.indication`` is Chinese and AI enrich for
``clinicaltrials_condition_term_en`` times out, search historically used the
Chinese string and returned zero studies (e.g. ``IgA肾病`` → 0 vs
``IgA nephropathy`` → 270+).

This module is deterministic and fail-open: unknown Chinese labels keep the
original text so callers can surface a user-facing gap, but known aliases
always resolve.
"""
from __future__ import annotations

import re
from typing import Optional

# Non-oncology first; expand as product covers more therapeutic areas.
# Keys are normalized (lowercase, stripped punctuation/spaces variants matched
# via ``_normalize_zh``).
_ZH_TO_EN_CONDITION: dict[str, str] = {
    # Nephrology / heme
    "iga肾病": "IgA nephropathy",
    "iga 肾病": "IgA nephropathy",
    "免疫球蛋白a肾病": "IgA nephropathy",
    "阵发性睡眠性血红蛋白尿症": "paroxysmal nocturnal hemoglobinuria",
    "阵发性睡眠性血红蛋白尿症（pnh）": "paroxysmal nocturnal hemoglobinuria",
    "pnh": "paroxysmal nocturnal hemoglobinuria",
    # GI / derm / rheum / resp (build + wave indications)
    "溃疡性结肠炎": "ulcerative colitis",
    "克罗恩病": "Crohn's disease",
    "慢性鼻窦炎伴鼻息肉": "chronic rhinosinusitis with nasal polyps",
    "慢性鼻-鼻窦炎伴鼻息肉": "chronic rhinosinusitis with nasal polyps",
    "特应性皮炎": "atopic dermatitis",
    "类风湿关节炎": "rheumatoid arthritis",
    "银屑病": "psoriasis",
    "斑块状银屑病": "plaque psoriasis",
    "强直性脊柱炎": "ankylosing spondylitis",
    "支气管哮喘": "asthma",
    "哮喘": "asthma",
    "系统性红斑狼疮": "systemic lupus erythematosus",
    "慢性荨麻疹": "chronic urticaria",
    "慢性自发性荨麻疹": "chronic spontaneous urticaria",
    "原发性胆汁性胆管炎": "primary biliary cholangitis",
    "干眼症": "dry eye",
    "干眼": "dry eye",
    "特发性肺纤维化": "idiopathic pulmonary fibrosis",
    "多发性硬化": "multiple sclerosis",
    "重症肌无力": "myasthenia gravis",
    "全身型重症肌无力": "generalized myasthenia gravis",
    "阿尔茨海默病": "Alzheimer's disease",
    "阿尔茨海默症": "Alzheimer's disease",
    # Additional high-frequency non-oncology
    "2型糖尿病": "type 2 diabetes mellitus",
    "二型糖尿病": "type 2 diabetes mellitus",
    "高血压": "hypertension",
    "心力衰竭": "heart failure",
    "冠心病": "coronary artery disease",
    "慢性阻塞性肺疾病": "chronic obstructive pulmonary disease",
    "慢阻肺": "chronic obstructive pulmonary disease",
    "骨关节炎": "osteoarthritis",
    "痛风": "gout",
    "银屑病关节炎": "psoriatic arthritis",
    "幼年特发性关节炎": "juvenile idiopathic arthritis",
    "炎性肠病": "inflammatory bowel disease",
    "非酒精性脂肪性肝炎": "nonalcoholic steatohepatitis",
    "nash": "nonalcoholic steatohepatitis",
    "偏头痛": "migraine",
    "癫痫": "epilepsy",
    "帕金森病": "Parkinson's disease",
    "抑郁症": "major depressive disorder",
    "精神分裂症": "schizophrenia",
    "痤疮": "acne",
    "白癜风": "vitiligo",
    "斑秃": "alopecia areata",
    "荨麻疹": "urticaria",
    "过敏性鼻炎": "allergic rhinitis",
    "季节性过敏性鼻炎": "seasonal allergic rhinitis",
}


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _normalize_zh(text: str) -> str:
    value = (text or "").strip().lower()
    value = value.replace("（", "(").replace("）", ")")
    value = re.sub(r"\s+", "", value)
    return value


def contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _lookup_known_alias(value: str) -> tuple[str, str] | None:
    """Return an English alias for an exact or qualified Chinese label.

    Clinical indications commonly add severity/activity/population qualifiers
    (for example ``中重度活动性克罗恩病``).  Those qualifiers should not turn
    a known disease into a Chinese ``query.cond`` miss.  Longest-first
    containment keeps the mapping deterministic while preferring a specific
    disease over a broad parent term.
    """
    normalized = _normalize_zh(value)
    if not normalized:
        return None
    direct = _ZH_TO_EN_CONDITION.get(normalized)
    if direct:
        return direct, "exact"
    stripped = re.sub(r"[（(][^）)]*[）)]", "", value or "").strip()
    stripped_normalized = _normalize_zh(stripped)
    if stripped_normalized != normalized:
        direct = _ZH_TO_EN_CONDITION.get(stripped_normalized)
        if direct:
            return direct, "stripped"
        normalized = stripped_normalized
    aliases = sorted(
        _ZH_TO_EN_CONDITION.items(),
        key=lambda item: len(_normalize_zh(item[0])),
        reverse=True,
    )
    for alias, mapped in aliases:
        alias_normalized = _normalize_zh(alias)
        if not contains_cjk(alias_normalized):
            continue
        if len(alias_normalized) >= 2 and alias_normalized in normalized:
            return mapped, "contains"
    return None


def resolve_clinicaltrials_condition_term(
    *,
    indication: str = "",
    clinicaltrials_condition_term: str = "",
) -> tuple[str, Optional[str]]:
    """Return ``(resolved_term, alias_source)``.

    Prefer an already-English ``clinicaltrials_condition_term``. Otherwise map
    Chinese indication / term via the alias table. ``alias_source`` is a short
    provenance string when a deterministic alias was applied; otherwise None.
    """
    preferred = (clinicaltrials_condition_term or "").strip()
    indication_text = (indication or "").strip()

    if preferred and not contains_cjk(preferred):
        return preferred, None

    for candidate, source in (
        (preferred, "clinicaltrials_condition_term"),
        (indication_text, "indication"),
    ):
        if not candidate:
            continue
        alias = _lookup_known_alias(candidate)
        if alias:
            mapped, match_kind = alias
            suffix = "" if match_kind == "exact" else f":{match_kind}"
            return mapped, f"zh_alias:{source}{suffix}"

    # Already English indication
    if indication_text and not contains_cjk(indication_text):
        return indication_text, None

    # Fail-open: keep preferred Chinese / original so UI can show the gap.
    fallback = preferred or indication_text
    return fallback, None
