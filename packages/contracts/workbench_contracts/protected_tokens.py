"""Deterministic identity-token checks for medical-writing revisions.

This module has no service dependencies so persisted contracts can verify a
candidate against its selected source during cold-load validation.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class ProtectedToken:
    kind: str
    text: str
    normalized: str
    start: int
    end: int

    @property
    def signature(self) -> tuple[str, str]:
        return self.kind, self.normalized


@dataclass(frozen=True)
class ProtectedTokenCheck:
    source_tokens: tuple[ProtectedToken, ...]
    proposal_tokens: tuple[ProtectedToken, ...]
    missing: tuple[ProtectedToken, ...]
    added: tuple[ProtectedToken, ...]
    order_changed: bool

    @property
    def violated(self) -> bool:
        return bool(self.missing or self.order_changed)

    @property
    def status(self) -> str:
        if self.violated:
            return "violated"
        if self.added:
            return "unresolved"
        return "verified"


_DASHES = "‐‑‒–—−"
_NUM = (
    r"(?:"
    r"\d+(?:[.,]\d+)?\s*[×x]\s*10\s*(?:\^|\u207b)?\s*[+-]?\d+"
    r"|\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?"
    r")"
)
_CHINESE_NUM = r"(?:半|[零〇一二三四五六七八九十百千万两]+(?:点[零〇一二三四五六七八九十百千万两]+)?)"
_CN_BOUND_PREFIX = r"(?:不超过|不多于|不少于|不低于|至少|至多|大于|小于|高于|低于|超过|约为|约)"
_CN_BOUND_SUFFIX = r"(?:以上|以下)"
_METRIC_VARIABLE = r"(?:[A-Za-z][A-Za-z0-9._-]{0,15})"
_METRIC_COMPARATOR = r"(?:<=|>=|<|>|≤|≥)"
_SIGNED_NUM = rf"(?:(?:<=|>=|[-+±{_DASHES}<>≤≥])\s*)?{_NUM}"
_RANGE = rf"(?:\s*[-{_DASHES}]\s*{_NUM})?"
_UNIT_BASE = (
    r"(?:mmol|mol|μmol|umol|nmol|pmol|mg|g|kg|μg|ug|ng|pg|mL|μL|uL|nL|pL|dL|L|mmHg|mm|cm|km|m|"
    r"cmH2O|m2|m\^2|cm2|cm\^2|°C|IU|U|bpm|M|mM|μM|uM|nM|pM|%|％|"
    r"day|days|week|weeks|month|months|year|years|ms|μs|us|ns|ps|d|h|min|sec|s|"
    r"毫克|微克|克|千克|毫升|微升|纳克|皮克|摩尔|毫摩尔|升|"
    r"小时|分钟|分|天|日|周|月|年|岁|例|人|名|次|剂|片|粒|秒"
    r")"
)
_UNIT_COMPONENT = (
    r"(?:[A-Za-zμµ][A-Za-zμµ0-9^²³⁻-]*|"
    r"毫克|微克|克|千克|毫升|微升|纳克|皮克|摩尔|毫摩尔|升|"
    r"小时|分钟|分|天|日|周|月|年|岁|例|人|名|次|剂|片|粒|秒|"
    r"[%％°]+)"
)
_UNIT = (
    rf"(?:{_UNIT_BASE}(?:\s*[/·*]\s*{_UNIT_COMPONENT})*"
    rf"|/(?:{_UNIT_COMPONENT})(?:\s*[/·*]\s*{_UNIT_COMPONENT})*)"
)

# Earlier patterns own the span before generic numeric/term patterns see it.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "citation",
        re.compile(
            r"(?<![A-Za-z0-9_])[\[［]\s*\d{1,4}"
            rf"(?:\s*[-{_DASHES}]\s*\d{{1,4}})?"
            rf"(?:\s*[,，]\s*\d{{1,4}}(?:\s*[-{_DASHES}]\s*\d{{1,4}})?)*"
            r"\s*[\]］](?![A-Za-z0-9_])"
        ),
    ),
    (
        "cross_reference",
        re.compile(
            r"(?<![A-Za-z0-9_])(?:第\s*(?:\d+(?:\.\d+)*|"
            r"[IVXLCDM]+|[一二三四五六七八九十百千万]+)\s*(?:章|节|章节|条|部分|页)"
            r"|(?:表|图|附录|Table|Tables|Figure|Figures|Fig\.?)\s*"
            r"(?:[A-Za-z]?\d+(?:[.-]\d+)*[A-Za-z]?|"
            r"[IVXLCDM]+|[一二三四五六七八九十百千万]+))(?![A-Za-z0-9_])",
            re.IGNORECASE,
        ),
    ),
    (
        "controlled_term",
        re.compile(
            rf"(?<![A-Za-z0-9]){_METRIC_VARIABLE}\s*{_METRIC_COMPARATOR}\s*"
            rf"{_NUM}{_RANGE}(?:\s*{_UNIT})?(?![A-Za-z0-9/·*])"
        ),
    ),
    (
        "numeric_unit",
        re.compile(
            rf"(?<![A-Za-z0-9])百分之{_CHINESE_NUM}(?![A-Za-z0-9])"
        ),
    ),
    (
        "numeric_unit",
        re.compile(
            rf"(?<![A-Za-z0-9]){_CHINESE_NUM}\s*{_UNIT}(?:半)?"
            r"(?![A-Za-z0-9/·*])"
        ),
    ),
    (
        "numeric_unit",
        re.compile(
            rf"(?<![A-Za-z0-9])每(?:次|周|日|天|月|年|小时|分钟|季度)\s*"
            rf"{_CHINESE_NUM}\s*(?:次|剂|回|片|粒)(?:半)?(?![A-Za-z0-9])"
        ),
    ),
    (
        "numeric_unit",
        re.compile(
            rf"(?<![A-Za-z0-9]){_CN_BOUND_PREFIX}\s*{_SIGNED_NUM}{_RANGE}\s*{_UNIT}"
            rf"\s*{_CN_BOUND_SUFFIX}?(?![A-Za-z0-9/·*])"
        ),
    ),
    (
        "numeric_unit",
        re.compile(
            rf"(?<![A-Za-z0-9]){_SIGNED_NUM}{_RANGE}\s*{_UNIT}"
            rf"\s*{_CN_BOUND_SUFFIX}(?![A-Za-z0-9/·*])"
        ),
    ),
    (
        "numeric_unit",
        re.compile(
            rf"(?<![A-Za-z0-9])(?:≈|~|约)\s*{_SIGNED_NUM}{_RANGE}\s*{_UNIT}"
            r"(?![A-Za-z0-9/·*])"
        ),
    ),
    (
        "numeric_unit",
        re.compile(
            rf"(?<![A-Za-z0-9]){_SIGNED_NUM}{_RANGE}\s*{_UNIT}"
            r"(?![A-Za-z0-9/·*])",
            re.IGNORECASE,
        ),
    ),
    (
        "controlled_term",
        re.compile(
            r"(?<![A-Za-z0-9])[A-Za-z]{2,}(?:[-‐‑‒–—−]?\d+)?[-‐‑‒–—−]?[α-ωΑ-Ω]\d*"
            r"(?![A-Za-z0-9])"
        ),
    ),
    (
        "controlled_term",
        re.compile(
            r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9-]*[+−±-](?![A-Za-z0-9])"
        ),
    ),
    (
        "controlled_term",
        re.compile(
            r"(?<![A-Za-z0-9])[A-Za-z]+\d+[A-Za-z0-9]*(?![A-Za-z0-9])"
        ),
    ),
    (
        "controlled_term",
        re.compile(
            rf"(?<![A-Za-z0-9])(?:[IVXLCDM]+|{_CHINESE_NUM})\s*期"
            r"(?![A-Za-z0-9])"
        ),
    ),
    (
        "controlled_term",
        re.compile(
            rf"(?<![A-Za-z0-9])Phase\s*(?:[0-9]+|[IVXLCDM]+|{_CHINESE_NUM})"
            r"(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
    ),
    (
        "controlled_term",
        re.compile(
            r"(?<![A-Za-z0-9])[A-Za-z]\s*(?:组|臂|队列|层)(?![A-Za-z0-9])"
        ),
    ),
    (
        "controlled_term",
        re.compile(
            r"(?<![A-Za-z0-9])(?:Arm|Cohort)\s*[A-Za-z0-9]+(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
    ),
    (
        "controlled_term",
        re.compile(
            r"(?<![A-Za-z0-9])(?:Group|Part)\s*[A-Za-z0-9]+(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
    ),
    (
        "controlled_term",
        re.compile(
            r"(?<![A-Za-z0-9])(?:[cgmnpr])\.\d+(?:_\d+)?"
            r"(?:[+-]\d+)?[A-Za-z_*?=]+(?:>[A-Za-z_*?=]+)?"
            r"(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
    ),
    (
        "controlled_term",
        re.compile(
            r"(?<![A-Za-z0-9])(?:\d{1,2}|[XY])(?:p|q)\d+(?:\.\d+)*"
            r"(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
    ),
    (
        "controlled_term",
        re.compile(
            r"(?<![A-Za-z0-9])(?:qd|bid|tid|qid|qhs|qod|prn|stat)"
            r"(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
    ),
    (
        "controlled_term",
        re.compile(
            r"(?<![A-Za-z0-9])[α-ωΑ-Ω](?=\s*(?:受体|细胞|链|亚基|通路))"
        ),
    ),
    (
        "controlled_term",
        re.compile(
            r"(?<![A-Za-z0-9])(?:Cmax|Tmax|AUC\d*|Css|Cmin|Ctrough|T1/2|t1/2)"
            r"(?![A-Za-z0-9])"
        ),
    ),
    (
        "controlled_term",
        re.compile(
            r"(?<![A-Za-z0-9])(?:[A-Z]{2,}[A-Z0-9]*|[a-z][A-Z]{2,}[A-Za-z0-9]*"
            r"|[A-Za-z0-9]+-[A-Za-z0-9-]+|[A-Za-z]+\d+[A-Za-z]*)(?![A-Za-z0-9])"
        ),
    ),
    (
        "numeric",
        re.compile(
            rf"(?<![A-Za-z0-9]){_SIGNED_NUM}(?![A-Za-z0-9])"
        ),
    ),
)


def _normalize_token(value: str, kind: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = (
        normalized.replace("−", "-")
        .replace("‐", "-")
        .replace("‑", "-")
        .replace("‒", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("，", ",")
    )
    normalized = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", normalized)
    normalized = re.sub(r"(?<=\d),(?=\d{1,2}(?:\D|$))", ".", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    if kind in {"numeric_unit", "cross_reference"}:
        normalized = normalized.casefold() if kind == "cross_reference" else normalized
    if kind == "numeric_unit":
        normalized = re.sub(
            r"(?<=\d)[xX](?=\s*10(?:\^|\d))",
            "×",
            normalized,
        )
        normalized = re.sub(r"\b(cm|m)\^2\b", r"\g<1>2", normalized)
        normalized = re.sub(r"(?<![A-Za-z])uM(?![A-Za-z])", "μM", normalized)
        normalized = re.sub(r"(?<![A-Za-z])uL(?![A-Za-z])", "μL", normalized)
        normalized = re.sub(r"(?<![A-Za-z])umol(?![A-Za-z])", "μmol", normalized)
        normalized = normalized.replace("µ", "μ")
        normalized = re.sub(r"^(?:约为|约|~)", "≈", normalized)
        normalized = re.sub(r"^(?:至少|不少于|不低于|>=|≥)", "≥", normalized)
        normalized = re.sub(r"^(?:至多|不超过|不多于|<=|≤)", "≤", normalized)
        normalized = re.sub(r"^(?:大于|超过|高于|>)", ">", normalized)
        normalized = re.sub(r"^(?:小于|低于|<)", "<", normalized)
        if normalized.endswith("以上"):
            normalized = "≥" + normalized[:-2]
        elif normalized.endswith("以下"):
            normalized = "≤" + normalized[:-2]
        # Only units whose case is not semantically meaningful are folded.
        # M/m, mM/mm and nM/nm deliberately remain distinct.
        for unit in (
            "mmol",
            "mol",
            "mg",
            "g",
            "kg",
            "ug",
            "ng",
            "pg",
            "ml",
            "dl",
            "l",
            "mmhg",
            "cm",
            "km",
            "iu",
            "bpm",
            "day",
            "days",
            "week",
            "weeks",
            "month",
            "months",
            "year",
            "years",
            "ms",
            "us",
            "ns",
            "ps",
            "min",
            "sec",
        ):
            normalized = re.sub(
                rf"(?<![A-Za-z]){unit}(?![A-Za-z])",
                unit,
                normalized,
                flags=re.IGNORECASE,
            )
        normalized = re.sub(
            r"(?<![A-Za-z])(?:μg|µg|ug)(?![A-Za-z])",
            "μg",
            normalized,
            flags=re.IGNORECASE,
        )
        if re.fullmatch(r"(?i)(qd|bid|tid|qid|qhs|qod|prn|stat)", normalized):
            normalized = normalized.casefold()
    elif kind == "controlled_term":
        if re.match(r"^[pP](?=[<>≤≥])", normalized):
            normalized = "p" + normalized[1:]
        normalized = normalized.replace("<=", "≤").replace(">=", "≥")
        normalized = re.sub(r"\b(cm|m)\^2\b", r"\g<1>2", normalized)
        if re.fullmatch(r"(?i)(qd|bid|tid|qid|qhs|qod|prn|stat)", normalized):
            normalized = normalized.casefold()
        elif re.match(r"(?i)^(?:phase|arm|cohort|group|part)[A-Za-z0-9]+$", normalized):
            normalized = normalized.casefold()
    return normalized


def extract_protected_tokens(text: str) -> tuple[ProtectedToken, ...]:
    """Extract non-overlapping identity tokens in deterministic source order."""

    value = str(text or "")
    # NFKC matching makes fullwidth Latin/digits and compatibility symbols
    # equivalent while keeping one deterministic token identity space.
    normalized_parts: list[str] = []
    normalized_starts: list[int] = []
    normalized_ends: list[int] = []
    for original_index, character in enumerate(value):
        part = unicodedata.normalize("NFKC", character)
        normalized_parts.append(part)
        normalized_starts.extend([original_index] * len(part))
        normalized_ends.extend([original_index + 1] * len(part))
    matching_value = "".join(normalized_parts)
    candidates: list[tuple[int, int, int, str, str]] = []
    for priority, (kind, pattern) in enumerate(_PATTERNS):
        for match in pattern.finditer(matching_value):
            candidates.append(
                (match.start(), match.end(), priority, kind, match.group(0))
            )
    candidates.sort(key=lambda item: (item[0], item[2], -(item[1] - item[0])))
    occupied: list[tuple[int, int]] = []
    tokens: list[ProtectedToken] = []
    for start, end, _priority, kind, _raw in candidates:
        if any(
            start < other_end and end > other_start
            for other_start, other_end in occupied
        ):
            continue
        occupied.append((start, end))
        if start >= len(normalized_starts) or end <= start:
            continue
        original_start = normalized_starts[start]
        original_end = normalized_ends[end - 1]
        raw = value[original_start:original_end]
        tokens.append(
            ProtectedToken(
                kind=kind,
                text=raw,
                normalized=_normalize_token(raw, kind),
                start=original_start,
                end=original_end,
            )
        )
    tokens.sort(key=lambda token: (token.start, token.end, token.kind))
    return tuple(tokens)


def _unmatched_tokens(
    source_tokens: tuple[ProtectedToken, ...],
    proposal_tokens: tuple[ProtectedToken, ...],
) -> tuple[tuple[ProtectedToken, ...], tuple[ProtectedToken, ...]]:
    available = Counter(token.signature for token in proposal_tokens)
    missing: list[ProtectedToken] = []
    for token in source_tokens:
        if available[token.signature] > 0:
            available[token.signature] -= 1
        else:
            missing.append(token)

    available_source = Counter(token.signature for token in source_tokens)
    added: list[ProtectedToken] = []
    for token in proposal_tokens:
        if available_source[token.signature] > 0:
            available_source[token.signature] -= 1
        else:
            added.append(token)
    return tuple(missing), tuple(added)


def check_protected_tokens(source_text: str, proposal_text: str) -> ProtectedTokenCheck:
    """Compare source/proposal identity tokens without clinical interpretation."""

    source_tokens = extract_protected_tokens(source_text)
    proposal_tokens = extract_protected_tokens(proposal_text)
    missing, added = _unmatched_tokens(source_tokens, proposal_tokens)
    proposal_signatures = [token.signature for token in proposal_tokens]
    cursor = 0
    sequence_failed = False
    for token in source_tokens:
        try:
            cursor = proposal_signatures.index(token.signature, cursor) + 1
        except ValueError:
            sequence_failed = True
            break
    order_changed = bool(not missing and sequence_failed)
    return ProtectedTokenCheck(
        source_tokens=source_tokens,
        proposal_tokens=proposal_tokens,
        missing=missing,
        added=added,
        order_changed=order_changed,
    )


def protected_token_issue_dicts(check: ProtectedTokenCheck) -> list[dict[str, str]]:
    """Return stable, auditable issue payloads for the Workbench contract."""

    issues: list[dict[str, str]] = []
    for token in check.missing:
        issues.append(
            {
                "kind": token.kind,
                "source_text": token.text,
                "proposal_text": "",
                "reason_code": "protected_token_missing",
                "message": f"候选缺少源文本中的受保护{token.kind}：{token.text}",
            }
        )
    if check.order_changed:
        issues.append(
            {
                "kind": "sequence",
                "source_text": "、".join(token.text for token in check.source_tokens),
                "proposal_text": "、".join(token.text for token in check.proposal_tokens),
                "reason_code": "protected_token_order_changed",
                "message": "候选改变了受保护数字/术语/引用的相对顺序。",
            }
        )
    for token in check.added:
        issues.append(
            {
                "kind": token.kind,
                "source_text": "",
                "proposal_text": token.text,
                "reason_code": "protected_token_added_unresolved",
                "message": f"候选新增受保护{token.kind}，需要医学经理核验来源：{token.text}",
            }
        )
    issues.sort(
        key=lambda item: (
            item["reason_code"],
            item["kind"],
            item["source_text"],
            item["proposal_text"],
        )
    )
    return issues
