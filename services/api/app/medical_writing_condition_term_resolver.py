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
    # R27 第1轮末修订 NEW-P0-01：现场（R1-A 难治性/不明原因慢性咳嗽）无别名
    # 可映射即 fail-open 放行复杂中文串 → CT.gov query.cond 表达式 400。
    "慢性咳嗽": "chronic cough",
    "难治性慢性咳嗽": "refractory chronic cough",
    "不明原因慢性咳嗽": "chronic cough",
    "良性前列腺增生": "benign prostatic hyperplasia",
    "前列腺增生": "benign prostatic hyperplasia",
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


# ---- R27 NEW-P0-01：英文段抽取与 query.cond 安全化 -----------------------
#
# CT.gov 的 query.cond 按表达式解析：全角/半角括号、斜杠、AND/OR 保留字、
# 中日韩字符都会触发 "Too complicated query" 400。富化产物常形如
# 『难治性/不明原因慢性咳嗽（Refractory Chronic cough / Unexplained
# Chronic Cough，RCC/UCC）』——括注里恰好有可用的英文条件词。

_QUERY_COND_RESERVED_WORDS = frozenset({"AND", "OR", "NOT"})
_QUERY_COND_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")
_CJK_CLASS_RE = re.compile(r"[\u3400-\u9fff]")


def extract_english_condition_phrase(value: str) -> str:
    """Return the first pure-English phrase usable as ``query.cond``.

    Splits the raw string on brackets/slashes/commas/semicolons and returns
    the first segment whose tokens are all ASCII words (reserved CT.gov
    operators dropped). Empty string when no such segment exists.
    """
    cleaned = re.sub(r"[（）()\[\]【】]", " ", value or "")
    segments = re.split(r"[/、，,;；]", cleaned)
    for segment in segments:
        tokens = [
            token
            for token in segment.split()
            if _QUERY_COND_TOKEN_RE.fullmatch(token)
            and token.upper() not in _QUERY_COND_RESERVED_WORDS
        ]
        if tokens:
            return " ".join(tokens)
    return ""


def sanitize_condition_query_term(value: str) -> str:
    """Sanitize any candidate condition term for CT.gov ``query.cond``.

    Known-clean English phrases pass through unchanged; mixed/CJK strings
    degrade to the first embedded English phrase; strings with no usable
    English phrase raise :class:`ValueError` with a human-actionable message
    (the API layer already maps ValueError to 422) instead of forwarding a
    guaranteed-400 expression to ClinicalTrials.gov.
    """
    raw = (value or "").strip()
    if not raw:
        raise ValueError("检索条件为空：请先补充有效的英文条件词后重试。")
    phrase = extract_english_condition_phrase(raw)
    if phrase:
        return phrase
    raise ValueError(
        "检索条件过于复杂（含括号/斜杠/保留字或非英文词元），且未包含可"
        "自动提取的英文条件词；请修改条件词（例如使用标准英文病名）后重试。"
    )


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
        # R27 NEW-P0-01②：含中文的混合串若带 ASCII 英文括注/英文段，优先
        # 抽取该英文段——它是AI对该完整限定标签的英文裁定，比别名表的
        # 子串包含命中（如『不明原因慢性咳嗽』→chronic cough）更忠实、
        # 更具体。纯中文串继续走别名表。
        if contains_cjk(candidate):
            english_phrase = extract_english_condition_phrase(candidate)
            if english_phrase:
                return english_phrase, f"en_extract:{source}"
        alias = _lookup_known_alias(candidate)
        if alias:
            mapped, match_kind = alias
            suffix = "" if match_kind == "exact" else f":{match_kind}"
            return mapped, f"zh_alias:{source}{suffix}"

    # Already English indication
    if indication_text and not contains_cjk(indication_text):
        return indication_text, None

    # R27 NEW-P0-01②：混合串（中文+ASCII括注/英文段）时抽取英文段作
    # 条件词——fail-open 原样放行复杂中文串会被 CT.gov 当表达式解析 400。
    fallback = preferred or indication_text
    if fallback and contains_cjk(fallback):
        english_phrase = extract_english_condition_phrase(fallback)
        if english_phrase:
            return english_phrase, "en_extract:clinicaltrials_condition_term"

    # Fail-open: keep preferred Chinese / original so UI can show the gap.
    return fallback, None
