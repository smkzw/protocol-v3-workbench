"""Production DeepSeek prefill adapter for AI-first authoring prefill.

This adapter implements :class:`PrefillRankingAdapter` and makes **one bulk**
structured DeepSeek request per prefill stage, rather than one model call per
field.  It verifies the returned model identity, proposes an English
ClinicalTrials.gov condition term as an unconfirmed candidate, and merges only
valid AI candidates into the deterministic package.

W2b-2 r2/r3 changes:

- The evidence catalog is the **sole** evidence input.  No registered_source_ids,
  no snapshot_hints, no legacy field-suggestion bypass.
- Every AI candidate requires at least one valid catalog claim binding;
  any binding failure rejects the entire candidate.
- ``_validate_value_pointer`` implements strict RFC 6901 multi-segment
  resolution: only ``~0``/``~1`` escapes, array index validation (no ``-``,
  no leading zeros, bounds check), and the resolved value must be an
  atomic leaf (str/bool/int/float), not a container.
- ``_all_atomic_values_bound`` recursively enumerates every non-empty
  atomic leaf under each target_path and checks coverage by canonical
  RFC 6901 pointer.
- ``_extract_package_target_paths`` is fail-closed: no fallback paths.
- The system prompt only references ``evidence_catalog.sent_entry_ids``.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping

from packages.contracts.workbench_contracts import (
    AuthoringPrefillCandidate,
    AuthoringPrefillEvidenceRef,
    AuthoringPrefillFieldCandidates,
    AuthoringPrefillPackage,
    MedicalWritingAuthoringJourney,
    WritingReferenceSearchSnapshot,
    WritingReferenceTrialCandidate,
)

from .medical_writing_authoring_prefill import (
    EXACT_FACT_PATHS,
    canonicalize_candidate_value,
    dedupe_materially_distinct,
    payload_sha256,
    select_safe_recommended_candidate_id,
)
from .medical_writing_authoring_prefill_evidence import build_evidence_catalog
from .medical_writing_authoring_prefill_evidence_binding import (
    PACKAGE_KEYS,
    MAX_PACKAGE_CANDIDATES_PER_KEY,
    MAX_FIELD_SUGGESTIONS_PER_FIELD,
    MAX_TOTAL_PAYLOAD_CHARS,
    build_round1_corpus_review_candidates,
    project_catalog_for_model,
    validate_and_rebind_candidates,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PrefillAiRunAudit:
    """Secret-free lineage for one completed independent-AI prefill call."""

    ai_run_id: str
    provider: str
    input_sha256: str
    output_sha256: str

    def as_package_update(self) -> dict[str, str]:
        return {
            "ai_run_id": self.ai_run_id,
            "ai_provider": self.provider,
            "ai_input_sha256": self.input_sha256,
            "ai_output_sha256": self.output_sha256,
        }


def _build_prefill_ai_run_audit(
    *,
    provider: Any | None,
    model_name: str,
    prompt_version: str,
    request_payload: dict[str, Any],
    raw_response: dict[str, Any],
) -> _PrefillAiRunAudit:
    """Create an internal run ID; retain only canonical input/output hashes."""
    provider_name = str(
        getattr(provider, "provider_name", "")
        or getattr(provider, "name", "")
        or type(provider).__name__
    ).strip()
    input_sha256 = payload_sha256(
        {
            "prompt_version": prompt_version,
            "system_prompt": _BULK_SYSTEM_PROMPT,
            "payload": request_payload,
        }
    )
    output_sha256 = payload_sha256(raw_response)
    ai_run_id = "mwprefillrun_" + payload_sha256(
        {
            "kind": "authoring_prefill_bulk",
            "provider": provider_name,
            "model_name": model_name,
            "prompt_version": prompt_version,
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
        }
    )[:24]
    return _PrefillAiRunAudit(
        ai_run_id=ai_run_id,
        provider=provider_name,
        input_sha256=input_sha256,
        output_sha256=output_sha256,
    )

# ---------------------------------------------------------------------------
# Prompt and model constants
# ---------------------------------------------------------------------------

PREFILL_AI_PROMPT_VERSION = "authoring_prefill_evidence_grounded_v7"
DEEPSEEK_PREFILL_MODEL = "deepseek-v4-flash"
# Max-reasoning DeepSeek V4 Flash prefill is a single, evidence-bounded bulk
# request.  The former generic 300 s provider budget was observed to expire at
# exactly 315 s (provider timeout + the local 15 s grace) before the provider
# returned, leaving an immutable ``unknown_outcome`` reservation.  Keep this
# route-specific budget below the global 30-minute profile ceiling while
# allowing the model enough time to finish its structured response.  A larger
# explicit ``WORKBENCH_AI_PREFILL_TIMEOUT_SECONDS`` value is honoured.
DEEPSEEK_PREFILL_TIMEOUT_SECONDS = 900.0

# ---------------------------------------------------------------------------
# F1 (preserved): Explicit minimal allowlist of fields the AI is allowed to
# propose for.  Identity fields are excluded.
# ---------------------------------------------------------------------------

_AI_ELIGIBLE_FIELDS: frozenset[str] = frozenset(
    {
        "framing.document_title",
        "framing.population_intent",
        "framing.design_pattern",
        "framing.intrinsic_objectives",
        "framing.development_regions",
        "framing.competitor_target_scope",
        "picos.population_summary",
        "picos.intervention_summary",
        "picos.comparator_summary",
        "picos.study_epochs",
        "picos.visit_strategy",
        "picos.design_archetype",
    }
)

_CONDITION_TERM_PATH = "framing.clinicaltrials_condition_term"

# ---------------------------------------------------------------------------
# D3: Exact-fact content gate — English + Chinese regulatory patterns.
# Parameterized as a list of (category, [patterns]) for maintainability.
# ---------------------------------------------------------------------------

_EXACT_FACT_DEFS: list[tuple[str, list[str]]] = [
    # Dose / 剂量
    ("dose", [
        r"\d+\s*(?:mg|kg|mcg|μg|g|ml|IU|mg/m2|mg/kg|mcg/kg|μg/kg)\b",
        r"\d+\s*(?:毫克|克|微克|国际单位)",
    ]),
    # Regimen / 频次 / 给药间隔
    ("regimen", [
        r"\b(?:Q\d+W|BID|TID|QD|Q\d+H|once\s+daily|twice\s+daily|three\s+times\s+daily)\b",
        r"(?:每日|每周|每\d+周|每日一次|每日两次|每周一次|隔日|每\d+小时)",
    ]),
    # Endpoint / 主要或关键次要终点
    ("endpoint", [
        r"\b(?:primary\s+endpoint|key\s+secondary|co-primary|secondary\s+endpoint)\b",
        r"(?:主要终点|关键次要终点|共同主要终点|次要终点)",
    ]),
    # AESI / 特别关注不良事件
    ("aesi", [
        r"\b(?:AESI|adverse\s+events?\s+of\s+special\s+interest)\b",
        r"(?:特别关注的不良事件|特别关注不良事件|AESI)",
    ]),
    # Sample size / 样本量 / 例受试者
    ("sample_size", [
        r"\b(?:N\s*=\s*\d|n\s*=\s*\d|sample\s+size\s+(?:of\s+)?(?:\d|approximately))",
        r"(?:样本量(?:为|约|共)?\s*\d|\d+\s*例(?:受试者|患者)|计划入组\s*\d+)",
    ]),
    # Washout / 洗脱期
    ("washout", [
        r"\b(?:washout|wash-out|wash\s+out)\s+period\b",
        r"(?:洗脱期|洗脱时间|清除期)",
    ]),
    # Threshold / 数值阈值 / 上下限
    ("threshold", [
        r"(?:≥|>=|≧|at\s+least)\s*\d+\s*%|threshold\s+of\s+\d|response\s+rate\s+of\s+\d",
        r"(?:阈值(?:为|不低于|超过)?\s*\d|≥\s*\d+\s*%|不超过\s*\d|至少\s*\d|不低于\s*\d+\s*%|超过\s*\d+\s*%)",
    ]),
    # Visit timing / 筛选期 / 基线 / 第N周 / 第N天 / 访视时间窗
    ("visit_timing", [
        r"\b(?:Week\s+\d+|Day\s+\d+|treatment\s+period\s+of\s+\d+\s+week|follow-up\s+of\s+\d+\s+(?:week|month))\b",
        r"(?:第\s*\d+\s*(?:周|天|月)|筛选期|基线(?:期|访视)?|访视时间窗|治疗期\s*\d+\s*周|随访\s*\d+\s*(?:周|月))",
    ]),
]

# Compile once at module load.
_EXACT_FACT_CONTENT_PATTERNS: list[tuple[str, list[re.Pattern[str]]]] = [
    (category, [re.compile(p, re.IGNORECASE) for p in patterns])
    for category, patterns in _EXACT_FACT_DEFS
]


def _detect_exact_fact_content(text: str) -> str | None:
    """Return the category name if *text* contains an exact-fact-like pattern.

    Covers English and Chinese regulatory writing (D3).  Returns ``None`` if no
    pattern matches.
    """
    if not text:
        return None
    for category, patterns in _EXACT_FACT_CONTENT_PATTERNS:
        for pattern in patterns:
            if pattern.search(text):
                return category
    return None


# ---------------------------------------------------------------------------
# L1: Language quality gate — reject whole-sentence English in non-condition
# candidates while preserving necessary English abbreviations and tokens.
# ---------------------------------------------------------------------------

# English tokens that are routinely retained in Chinese clinical trial
# documents.  These are NOT treated as "English prose" even when they appear
# without Chinese context.  The list covers drug codes, NCT IDs, common
# PK/PD abbreviations, and study-design acronyms.
_ENGLISH_ALLOWLIST_TOKENS: frozenset[str] = frozenset(
    {
        # Drug codes / investigational product identifiers
        "cms-d017", "cms-d018", "cms-ra-201", "cms-pnh-301",
        # Common PK/PD and study-design abbreviations
        "pk", "pd", "sad", "mad", "auc", "cmax", "tmax", "tlag",
        "t½", "qd", "bid", "tid", "q4w", "q2w", "q8w",
        "nct", "aesii", "aesi", "smq", "meddra", "icd",
        "acr20", "acr50", "acr70", "easi", "nrs", "pasi", "iga", "bsa",
        "egfr", "gfr", "alt", "ast", "bili", "cr", "hgb", "plt",
        "ldh", "aptt", "inr", "crp", "esr",
        "biomarker", "biomarkers",
        "nash", "pbc", "pnh", "aih", "ra", "sle", "axspa", "uc", "cd",
        "be", "sabd", "dvt", "pe", "vte", "mace",
        "sae", "teae", "aes", "susar",
        "ib", "csr", "sap", "cfr",
        "ich", "gcp", "sdtm", "adam", "cdisc", "tlf",
        # Units
        "mg", "kg", "mcg", "μg", "ml", "iu", "mmol", "nmol",
    }
)

# Disease / indication abbreviations commonly kept as-is in Chinese text.
_DISEASE_ABBREVS: frozenset[str] = frozenset(
    {"pnh", "ra", "sle", "axspa", "uc", "cd", "pss", "ssc", "crswnp",
     "pn", "ps", "hs", "che", "csu", "nash", "pbc", "aih", "copd"}
)

# Minimum number of non-allowlisted English words in a candidate that has no
# Chinese characters to be rejected as whole-sentence English.  A single real
# English word (e.g. "Study", "Adult", "randomized") without any surrounding
# Chinese context already means the candidate is not regulatory Chinese prose.
# Allowlisted abbreviations (CMS-D017, PNH, PK/PD, NCT IDs, units) do not
# count toward this threshold.
_MIN_ENGLISH_WORDS_FOR_REJECTION = 1


def _is_english_token(token: str) -> bool:
    """Check whether *token* is a single non-allowlisted English word."""
    token_lower = token.lower().strip(".,;:!?()[]{}\"'—-–")
    if not token_lower:
        return False
    if not all(c.isascii() and c.isalpha() for c in token_lower):
        return False
    if token_lower in _ENGLISH_ALLOWLIST_TOKENS:
        return False
    # NCT IDs like NCT01234567
    if re.match(r"^nct\d+$", token_lower):
        return False
    return True


def _has_chinese(text: str) -> bool:
    """Check whether *text* contains any CJK character."""
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _detect_whole_sentence_english(text: str) -> bool:
    """Return True if *text* lacks Chinese and contains real English prose.

    A candidate value is considered whole-sentence English when:
    1. It contains NO Chinese characters at all, AND
    2. It has at least _MIN_ENGLISH_WORDS_FOR_REJECTION non-allowlisted
       English words.

    Abbreviations like CMS-D017, PK/PD, SAD/MAD, NCT IDs, and units are
    NOT rejected because they are in the allowlist and do not count as
    English prose.
    """
    if not text or not text.strip():
        return False
    # If any Chinese character present, it is not whole-sentence English.
    if _has_chinese(text):
        return False
    # Tokenize by whitespace.
    tokens = text.strip().split()
    if not tokens:
        return False
    english_word_count = sum(1 for token in tokens if _is_english_token(token))
    return english_word_count >= _MIN_ENGLISH_WORDS_FOR_REJECTION


# ---------------------------------------------------------------------------
# L2: Unconfirmed design-fact gate — reject candidates that assert
# unconfirmed design or population facts without source evidence.
# ---------------------------------------------------------------------------

# Design/population keywords that constitute unconfirmed facts when asserted
# without a cited source.  Both English and Chinese patterns are listed.
_UNCONFIRMED_FACT_KEYWORDS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        # Population age
        r"\b(?:adult|adults|pediatric|children|adolescent)\b",
        r"(?:成人|儿童|青少年|老年人)",
        # Randomization
        r"\b(?:randomized|randomised|randomization|randomisation)\b",
        r"(?:随机)",
        # Blinding
        r"\b(?:double[\s-]?blind|single[\s-]?blind|open[\s-]?label|masked|unmasked)\b",
        r"(?:双盲|单盲|开放标签|盲态)",
        # Comparator
        r"\b(?:placebo[\s-]?controlled|active[\s-]?controlled|positive[\s-]?controlled)\b",
        r"(?:安慰剂对照|阳性对照|活性对照)",
        # Route of administration
        r"\b(?:oral(?:ly)?|intravenous|subcutaneous|intramuscular|topical|inhaled)\b",
        r"(?:口服|静脉注射|皮下注射|肌肉注射|外用|吸入)",
        # Line of therapy
        r"\b(?:first[\s-]?line|second[\s-]?line|treatment[\s-]?naive|treatment[\s-]?experienced)\b",
        r"(?:一线|二线|初治|经治|既往治疗)",
        # Severity / stage
        r"\b(?:moderate[\s-]to[\s-]?severe|severe|mild)\b",
        r"(?:中重度|重度|轻度)",
        # Mechanism / target
        r"\b(?:monoclonal\s+antibody|small\s+molecule|inhibitor|agonist|antagonist)\b",
        r"(?:单克隆抗体|小分子|抑制剂|激动剂|拮抗剂)",
        # MOA / target
        r"\b(?:factor\s+b|complement|properdin|cd\d+|il[\s-]?\d+)\b",
        r"(?:B因子|补体|备解素|靶点|机制)",
    ]
]


def _detect_unconfirmed_fact(text: str) -> bool:
    """Return True if *text* asserts unconfirmed design/population facts.

    This detects keywords like 成人/randomized/双盲/placebo/口服/单克隆抗体 etc.
    that go beyond the confirmed creation minimum (product, indication, phase).
    """
    if not text or not text.strip():
        return False
    for pattern in _UNCONFIRMED_FACT_KEYWORDS:
        if pattern.search(text):
            return True
    return False


# (name, display_label, candidate_pattern, evidence_pattern).  The display
# label is what the reader sees in the evidence gap when a substantive claim
# term is absent from every bound quote.
_CONTROLLED_TERM_EVIDENCE_RULES: tuple[
    tuple[str, str, re.Pattern[str], re.Pattern[str]], ...
] = tuple(
    (
        name,
        display,
        re.compile(candidate, re.IGNORECASE),
        re.compile(evidence, re.IGNORECASE),
    )
    for name, display, candidate, evidence in (
        ("adult", "成人/成年", r"(?:成人|成年|\badults?\b)", r"(?:成人|成年|\badults?\b)"),
        (
            "pediatric",
            "儿童/青少年/儿科",
            r"(?:儿童|青少年|儿科|\bpediatric\b|\bchildren\b|\badolescents?\b)",
            r"(?:儿童|青少年|儿科|\bpediatric\b|\bchildren\b|\badolescents?\b)",
        ),
        (
            "active_disease",
            "活动性疾病相关表述",
            r"(?:活动性|疾病活动度|活动度|\bactive\b)",
            r"(?:活动性|疾病活动度|活动度|\bactive\b)",
        ),
        (
            "diagnostic_confirmation",
            "临床/实验室检查确诊相关表述",
            r"(?:临床和实验室检查确诊|临床确诊|实验室检查确诊|确诊|\bdiagnos(?:is|ed|tic)\b)",
            r"(?:临床和实验室检查确诊|临床确诊|实验室检查确诊|确诊|\bdiagnos(?:is|ed|tic)\b)",
        ),
        (
            "eligibility_criteria",
            "入选/纳入标准相关表述",
            r"(?:入选标准|纳入标准|符合方案(?:规定)?|\beligibility\b|\binclusion\s+criteria\b)",
            r"(?:入选标准|纳入标准|符合方案(?:规定)?|\beligibility\b|\binclusion\s+criteria\b)",
        ),
        (
            "inadequate_response",
            "对标准治疗反应不佳相关表述",
            r"(?:应答不足|应答不佳|控制不佳|治疗失败|疗效不佳|反应不佳|"
            r"不耐受)",
            r"(?:应答不足|应答不佳|控制不佳|治疗失败|疗效不佳|反应不佳|"
            r"不耐受|inadequate(?:ly)?\s+(?:response|responder)|"
            r"insufficient\s+response|failed|intoleran)",
        ),
        (
            "achr_seropositive",
            "AChR抗体阳性相关表述",
            r"(?:AChR|乙酰胆碱受体(?:抗体)?|抗乙酰胆碱受体抗体)",
            r"(?:AChR|乙酰胆碱受体|acetylcholine\s+receptor)",
        ),
        (
            "ivig",
            "IVIG/静脉注射免疫球蛋白相关表述",
            r"(?:IVIG|静脉注射免疫球蛋白|静脉用免疫球蛋白|"
            r"静注人免疫球蛋白|丙种球蛋白)",
            r"(?:IVIG|静脉(?:注射|用)?免疫球蛋白|intravenous\s+immunoglobulin)",
        ),
        (
            "methotrexate",
            "甲氨蝶呤/MTX相关表述",
            r"(?:甲氨蝶呤|\bMTX\b)",
            r"(?:甲氨蝶呤|\bmethotrexate\b|\bMTX\b)",
        ),
        (
            "dmard",
            "改善病情抗风湿药/DMARD相关表述",
            r"(?:改善病情抗风湿药|\bDMARDs?\b)",
            r"(?:改善病情抗风湿药|\bDMARDs?\b)",
        ),
        (
            "background_treatment",
            "背景/基础治疗相关表述",
            r"(?:背景治疗|基础治疗)",
            r"(?:背景治疗|基础治疗|background\s+(?:therapy|treatment))",
        ),
        (
            "treatment_line_scope",
            "不限治疗线相关表述",
            r"(?:不限治疗线|不限线别|无治疗线限制|不限制治疗线|"
            r"any\s+line\s+of\s+therapy|unrestricted\s+(?:treatment\s+)?line)",
            r"(?:不限治疗线|不限线别|无治疗线限制|不限制治疗线|"
            r"any\s+line\s+of\s+therapy|unrestricted\s+(?:treatment\s+)?line)",
        ),
        (
            "washout",
            "洗脱期相关表述",
            r"(?:洗脱期|洗脱时间|清除期|washout)",
            r"(?:洗脱期|洗脱时间|清除期|washout|wash-out)",
        ),
        ("randomized", "随机相关表述", r"(?:随机|randomi[sz])", r"(?:随机|randomi[sz])"),
        (
            "blinding",
            "盲法相关表述",
            r"(?:双盲|单盲|盲态|开放标签|blind|masked|open-label)",
            r"(?:双盲|单盲|盲态|开放标签|blind|masked|open-label)",
        ),
        ("placebo", "安慰剂相关表述", r"(?:安慰剂|placebo)", r"(?:安慰剂|placebo)"),
        ("parallel", "平行分组相关表述", r"(?:平行分组|parallel)", r"(?:平行分组|parallel)"),
        (
            "multicenter",
            "多中心相关表述",
            r"(?:多中心|multic(?:enter|entre))",
            r"(?:多中心|multic(?:enter|entre))",
        ),
        (
            "efficacy",
            "有效性/疗效相关表述",
            r"(?:有效性|疗效|efficacy)",
            r"(?:有效性|疗效|efficacy|effectiveness)",
        ),
        ("safety", "安全性相关表述", r"(?:安全性|safety)", r"(?:安全性|safety)"),
        ("infection", "感染相关表述", r"(?:感染|infection)", r"(?:感染|infection)"),
        (
            "tuberculosis",
            "结核相关表述",
            r"(?:结核|tuberculosis|\bTB\b)",
            r"(?:结核|tuberculosis|\bTB\b)",
        ),
        (
            "malignancy",
            "恶性肿瘤相关表述",
            r"(?:恶性肿瘤|malignan|cancer)",
            r"(?:恶性肿瘤|malignan|cancer)",
        ),
        (
            "pregnancy",
            "妊娠/哺乳相关表述",
            r"(?:妊娠|哺乳|pregnan|lactat|breastfeed)",
            r"(?:妊娠|哺乳|pregnan|lactat|breastfeed)",
        ),
        (
            "hepatic_renal",
            "肝肾功能相关表述",
            r"(?:肝肾|肝功能|肾功能|hepatic|renal)",
            r"(?:肝肾|肝功能|肾功能|hepatic|renal)",
        ),
        (
            "acr_eular",
            "ACR/EULAR相关表述",
            r"(?:ACR\s*/\s*EULAR|ACR/EULAR)",
            r"(?:ACR\s*/\s*EULAR|ACR/EULAR)",
        ),
    )
)


# Worker_03 corrective: negation-aware controlled-term matching.
# A candidate that NEGATES a supported controlled term must never trigger
# the positive claim: "AChR抗体阴性" is not an AChR-seropositive claim,
# "未接受IVIG治疗" is not an IVIG-exposure claim, and "无治疗失败史" is not
# an inadequate-response claim.  Each rule's cleaners strip the negated
# spans from the candidate text BEFORE the rule's positive candidate
# pattern runs, so only a positive mention generates the claim and its
# reader-facing gap.  Evidence-side patterns are unchanged (positive-
# mention matching on the quote side).
_CONTROLLED_TERM_NEGATION_CLEANERS: dict[str, tuple[re.Pattern[str], ...]] = {
    "achr_seropositive": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            # Chinese 阴性 forms following the term
            # (AChR抗体阴性 / AChR血清阴性 / 乙酰胆碱受体抗体阴性 / 抗乙酰胆碱受体抗体阴性)
            r"(?:AChR(?:\s*-\s*Ab)?|乙酰胆碱受体(?:抗体)?|抗乙酰胆碱受体抗体)"
            r"(?:抗体|血清)?阴性",
            # Chinese negation before the term
            r"(?:无|没有|非)(?:抗)?AChR(?:抗体)?",
            # English negative forms following the term
            r"(?:anti-)?AChR(?:\s*-\s*Ab|\s+antibody)?\s+(?:is\s+)?"
            r"(?:seronegative|negative)",
            r"(?:anti-)?AChR\s+antibodies?\s+absent",
            # English negation preceding the term
            r"seronegative(?:\s+for)?\s+(?:anti-)?AChR",
            r"(?:without|no)\s+(?:anti-)?AChR(?:\s+antibodies?)?",
        )
    ),
    "ivig": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            # Chinese negation before the term
            r"(?:未接受|未使用|未用过|未经|未予|无|没有|不(?:予|使用|采用))"
            r"(?:过)?\s*(?:IVIG|静脉(?:注射|用)?免疫球蛋白|静注人免疫球蛋白|丙种球蛋白)",
            # Chinese negation after the term
            r"(?:IVIG|静脉(?:注射|用)?免疫球蛋白|静注人免疫球蛋白|丙种球蛋白)"
            r"(?:未使用|未用|未接受|停用|不再使用)",
            # English negation before/after the term
            r"(?:without|no|never|not)(?:\s+prior)?"
            r"(?:\s+(?:received|receiving|used|using|treated\s+with))?"
            r"\s+(?:IVIG|intravenous\s+immunoglobulin)",
            r"(?:IVIG|intravenous\s+immunoglobulin)[-\s]*(?:naive|naïve|free)",
        )
    ),
    "inadequate_response": tuple(
        re.compile(pattern)
        for pattern in (
            r"(?:无|未|没有|非|不)(?:出现过|发生过|出现|发生|存在|达到|伴|有过|任何|既往)?"
            r"(?:过)?(?:任何|既往)?"
            r"(?:应答不足|应答不佳|控制不佳|治疗失败|疗效不佳|反应不佳)",
            r"(?:无|未|没有|非)(?:出现过|发生过|出现|发生|存在|伴|有过|任何|既往)?"
            r"(?:过)?(?:药物|任何|既往)?不耐受",
        )
    ),
}


# Reader-facing prefix that marks a gap produced by a substantive candidate
# term absent from every bound quote.  Candidates carrying such a gap are
# surfaced as visible, non-adoptable alternatives and never occupy the
# recommended slot.
_UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX = "声称内容未在引用原文中出现："


def _evidence_semantically_supports_candidate(
    value: Any,
    preview: str,
    evidence_refs: list[AuthoringPrefillEvidenceRef],
) -> tuple[bool, str, list[str]]:
    """Reject controlled claims and numbers absent from bound source text.

    Returns ``(supported, reason, gap_notes)``.  ``gap_notes`` is non-empty
    only when a substantive controlled term (AChR / IVIG / inadequate
    response, …) is asserted by the candidate but absent from every bound
    quote: the candidate is not supported, but the reason is visible as a
    reader-facing evidence gap instead of a silent drop.  Numeric and
    exact-fact gates keep the hard-drop behavior.
    """
    candidate_text = f"{_value_to_text(value)} {preview}".strip()
    evidence_text = " ".join(
        str(ref.source_text or "") for ref in evidence_refs
    )
    if not candidate_text:
        return False, "candidate_has_no_text", []

    controlled_claims: list[
        tuple[str, str, re.Pattern[str], re.Pattern[str]]
    ] = []
    for (
        name,
        display,
        candidate_pattern,
        evidence_pattern,
    ) in _CONTROLLED_TERM_EVIDENCE_RULES:
        # Worker_03 corrective: negation-aware matching — strip this rule's
        # negated spans (AChR抗体阴性 / 未接受IVIG / 无治疗失败史, …) before
        # the positive pattern runs so a negated mention never produces a
        # positive controlled claim.
        rule_text = candidate_text
        for cleaner in _CONTROLLED_TERM_NEGATION_CLEANERS.get(name, ()):
            rule_text = cleaner.sub(" ", rule_text)
        if candidate_pattern.search(rule_text):
            controlled_claims.append(
                (name, display, candidate_pattern, evidence_pattern)
            )

    candidate_numbers = _extract_clinical_claim_numbers(candidate_text)
    evidence_numbers = _extract_clinical_claim_numbers(evidence_text)
    if not evidence_text.strip():
        if controlled_claims or candidate_numbers:
            return (
                False,
                "candidate_rejected_unconfirmed_fact_fail_closed:"
                "no_bound_source_text",
                [],
            )
        return True, "", []

    missing_terms: list[str] = []
    missing_names: list[str] = []
    for name, display, _candidate_pattern, evidence_pattern in controlled_claims:
        if not evidence_pattern.search(evidence_text):
            missing_terms.append(f"{_UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX}{display}")
            missing_names.append(name)
    if missing_terms:
        return (
            False,
            "candidate_rejected_unconfirmed_fact_fail_closed:"
            "controlled_term_not_in_bound_evidence:"
            + ",".join(missing_names),
            missing_terms,
        )

    unsupported_numbers = sorted(candidate_numbers - evidence_numbers)
    if unsupported_numbers:
        return (
            False,
            "candidate_rejected_unconfirmed_fact_fail_closed:"
            "numeric_claim_not_in_bound_evidence:"
            + ",".join(unsupported_numbers[:5]),
            [],
        )
    return True, "", []


def _extract_clinical_claim_numbers(text: str) -> set[str]:
    """Extract numeric claims without treating study identifiers as facts."""
    normalized = str(text or "")
    normalized = re.sub(r"\bNCT\d{8}\b", " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r"\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+\b",
        " ",
        normalized,
    )
    return set(re.findall(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?", normalized))


def _value_to_text(value: Any) -> str:
    """Flatten a structured_value to a single text string for language
    gating.  Handles str, list, dict, and other types by stable
    serialization."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, dict)):
        import json

        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _passes_language_and_evidence_gate(
    field_path: str,
    value: Any,
    preview: str,
    rationale: str,
    *,
    evidence_refs: list[AuthoringPrefillEvidenceRef],
    claim_bindings: list[Any] | None = None,
    evidence_status: str = "insufficient",
) -> tuple[bool, str, list[str]]:
    """Fail-closed quality gate for AI candidates.

    Returns ``(passed, reason, gap_notes)``.  When ``passed`` is False and
    ``gap_notes`` is empty, the candidate is hard-dropped from the result —
    it must never appear as a selectable candidate, not even as a
    non-recommended alternative.  When ``passed`` is False but ``gap_notes``
    is non-empty, a substantive controlled claim (AChR / IVIG / inadequate
    response, …) is absent from every bound quote: the caller keeps the
    candidate visible with those gaps and demotes it to a non-adoptable
    alternative instead of a silent drop.

    Language gate (L1) is applied **per field**, not on a concatenated
    blob.  A Chinese rationale must not mask an English value or preview.
    Each of structured_value, preview, and rationale is checked
    independently for whole-sentence English.

    Rules:
    - The condition-term path (``framing.clinicaltrials_condition_term``) is
      exempt from the language gate because it must be English.
    - Whole-sentence English in ANY of value/preview/rationale is rejected.
      A single non-allowlisted English word without Chinese context is
      sufficient.
    - Unconfirmed design/population facts (成人/随机/双盲/安慰剂对照/
      给药途径/治疗线/严重度/靶点机制 etc.) require server-validated
      claim-level catalog bindings. They remain candidate options, not current
      study facts, until the medical manager selects them.

    This gate does NOT affect:
    - Abbreviations like CMS-D017, PNH, PK/PD, SAD/MAD (allowlisted).
    - Deterministic candidates (the gate is only applied to AI candidates
      inside ``_merge_ai_candidates``).
    """
    # Condition term path is exempt — it must be English.
    if field_path == _CONDITION_TERM_PATH:
        return True, "", []

    # --- L1: Language gate — per-field, not concatenated ---
    # A Chinese rationale must not mask an English value or preview.
    value_str = _value_to_text(value)
    for field_label, field_text in (
        ("value", value_str),
        ("preview", preview),
        ("rationale", rationale),
    ):
        if _detect_whole_sentence_english(field_text):
            return (
                False,
                f"candidate_rejected_whole_sentence_english_{field_label}",
                [],
            )

    # --- L2: Unconfirmed fact gate — on combined text ---
    combined = f"{value_str} {preview} {rationale}"
    semantically_supported, semantic_reason, semantic_gaps = (
        _evidence_semantically_supports_candidate(
            value,
            preview,
            evidence_refs,
        )
    )
    if not semantically_supported:
        return False, semantic_reason, semantic_gaps

    if _detect_unconfirmed_fact(combined):
        bindings = list(claim_bindings or [])
        binding_status_ok = evidence_status in {
            "supported",
            "partially_supported",
        }
        binding_kinds = {
            str(getattr(binding, "support_kind", "") or "")
            for binding in bindings
        }
        if (
            evidence_refs
            and bindings
            and binding_status_ok
            and binding_kinds.intersection(
                {"competitor_option", "exact_fact", "normalized_enum"}
            )
        ):
            return True, "", []
        return (
            False,
            "candidate_rejected_unconfirmed_fact_fail_closed",
            [],
        )

    return True, "", []


def _has_unsupported_substantive_gap(
    candidate: AuthoringPrefillCandidate,
) -> bool:
    """True when *candidate* carries a substantive-claim gap produced by the
    semantic coverage check (controlled term absent from every bound quote).

    Such candidates are visible but must never occupy the recommended slot.
    """
    return any(
        str(gap).startswith(_UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX)
        for gap in (candidate.evidence_gaps or [])
    )


def _recommended_candidate_id_for_group(
    distinct: list[AuthoringPrefillCandidate],
) -> str:
    """Choose the recommended-slot candidate for an enriched group.

    Returns the first safe candidate (non-pending, no unsupported-substantive
    gap) or "" when every visible candidate is pending, manual-only, or
    otherwise unsafe — the group keeps all candidates but has no
    recommendation.  The recommended slot never points at a pending/manual/
    unsupported card.  Candidate roles are never mutated.
    """
    return select_safe_recommended_candidate_id(
        distinct,
        is_disqualified=_has_unsupported_substantive_gap,
    )


def _surface_unsupported_substantive_gap(
    candidate: AuthoringPrefillCandidate,
    gap_notes: list[str],
) -> AuthoringPrefillCandidate:
    """Keep a candidate whose substantive claim is absent from bound quotes.

    The candidate stays visible as a manual-only alternative carrying the
    reader-facing gap and an ``insufficient`` evidence status, so it can
    never be adopted as an unqualified alternative.  A role of
    ``recommended`` is demoted to ``alternative``; pending roles are never
    touched.
    """
    existing_gaps = [
        str(gap).strip()
        for gap in (candidate.evidence_gaps or [])
        if str(gap).strip()
    ]
    merged_gaps = list(
        dict.fromkeys(
            existing_gaps
            + [str(gap).strip() for gap in gap_notes if str(gap).strip()]
        )
    )[:20]
    updates: dict[str, Any] = {
        "evidence_gaps": merged_gaps,
        "evidence_status": "insufficient",
        "adoption_mode": "manual_only",
    }
    if str(candidate.recommendation_role or "").strip() == "recommended":
        updates["recommendation_role"] = "alternative"
    return candidate.model_copy(update=updates, deep=True)


# ---------------------------------------------------------------------------
# Evidence-confidence ranking: candidates with real source evidence rank
# above those with only AI provenance.
# ---------------------------------------------------------------------------


def _has_real_evidence(candidate: AuthoringPrefillCandidate) -> bool:
    """Return True if *candidate* carries at least one real evidence ref
    (not just AI rationale/limitations)."""
    return any(
        ref.source_id and ref.source_id not in (
            "framing.indication",
            "framing.investigational_product",
            "framing.study_phase",
        )
        or (ref.source_text and ref.source_text.strip())
        for ref in candidate.evidence_refs
    )


# ---------------------------------------------------------------------------
# D2: Registered source ID contract
# ---------------------------------------------------------------------------


def _collect_registered_source_ids(
    state: MedicalWritingAuthoringJourney,
) -> frozenset[str]:
    """Collect the set of source IDs registered in the project.

    AI candidates may cite these IDs as direct evidence for exact facts.  Any
    source ID not in this set is not registered and cannot serve as evidence.
    """
    ids: set[str] = set()
    if state.study_definition is not None:
        for artifact_id in state.study_definition.source_artifact_ids:
            sid = artifact_id.strip()
            if sid:
                ids.add(sid)
    ids.add("framing.indication")
    ids.add("framing.investigational_product")
    ids.add("framing.study_phase")
    return frozenset(ids)


def _extract_cited_source_ids(item: dict[str, Any]) -> list[str]:
    """Extract source IDs cited by an AI suggestion item."""
    source_ids = item.get("source_ids") or item.get("evidence_source_ids") or []
    if not isinstance(source_ids, list):
        return []
    return [sid.strip() for sid in source_ids if isinstance(sid, str) and sid.strip()]


def _filter_registered_ids(
    cited_ids: list[str],
    registered_source_ids: frozenset[str],
) -> list[str]:
    """Return only the cited IDs that are in the registered set."""
    return [sid for sid in cited_ids if sid in registered_source_ids]


# ---------------------------------------------------------------------------
# D4: Deterministic relevance screening — hard Protocol gate
# ---------------------------------------------------------------------------

# Only Protocol-bearing files qualify for the competitor protocol corpus.
_QUALIFYING_DOC_TYPES: frozenset[str] = frozenset(
    {"protocol", "protocol_sap"}
)


def _trial_has_qualifying_public_doc(
    trial: WritingReferenceTrialCandidate,
) -> tuple[bool, bool]:
    """Check whether a trial has a public Protocol and separately note SAP.

    Uses ``document_type`` as the primary structured check (D4).  Falls back to
    filename substring matching only when ``document_type`` is empty.

    Returns ``(has_protocol, has_sap)``.
    """
    has_protocol = False
    has_sap = False
    for doc in trial.public_documents:
        dtype = (doc.document_type or "").strip().lower()
        fname = (doc.filename or "").lower()
        # Primary: structured document_type.
        if dtype in _QUALIFYING_DOC_TYPES:
            has_protocol = True
            has_sap = dtype == "protocol_sap"
        elif dtype == "sap":
            has_sap = True
        elif not dtype:
            # Fallback: filename substring.
            if "protocol" in fname:
                has_protocol = True
            if "sap" in fname or "statistical analysis plan" in fname:
                has_sap = True
    return has_protocol, has_sap


def _screen_snapshot_candidates(
    candidates: list[WritingReferenceTrialCandidate],
    *,
    condition_term: str,
    phases: list[str],
    study_type: str,
) -> list[dict[str, Any]]:
    """Apply deterministic minimum relevance gates to snapshot candidates.

    D4: Public Protocol availability is a **hard gate** — standalone SAP does
    not qualify for the competitor protocol corpus. Only candidates that
    pass all gates are returned as structured hints for the model.
    """
    if not candidates:
        return []
    condition_lower = condition_term.lower().strip()
    phase_set = {p.upper() for p in phases}
    study_type_upper = study_type.upper()

    screened: list[dict[str, Any]] = []
    for trial in candidates:
        # Gate 1: condition match.
        trial_conditions = [c.lower().strip() for c in trial.conditions]
        condition_match = any(
            condition_lower in cond or cond in condition_lower
            for cond in trial_conditions
            if cond
        )
        if not condition_match and condition_lower:
            continue

        # Gate 2: phase match.
        trial_phases = {p.upper() for p in trial.phases}
        if phase_set and not trial_phases.intersection(phase_set):
            continue

        # Gate 3: study type match.
        if study_type_upper and trial.study_type.upper() != study_type_upper:
            continue

        # Gate 4 (D4 hard gate): must have a qualifying public Protocol.
        has_protocol, has_sap = _trial_has_qualifying_public_doc(trial)
        if not has_protocol:
            continue

        screened.append(
            {
                "nct_id": trial.nct_id,
                "official_title": (trial.official_title or trial.brief_title or "")[:300],
                "conditions": trial.conditions[:5],
                "phases": trial.phases,
                "study_type": trial.study_type,
                "lead_sponsor": trial.lead_sponsor,
                "has_public_protocol": has_protocol,
                "has_public_sap": has_sap,
                "overall_status": trial.overall_status,
            }
        )
    return screened


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class DeepSeekPrefillAdapter:
    """Bulk production DeepSeek adapter for authoring prefill ranking.

    Makes **one** bulk provider call per stage.  Exact clinical facts are never
    touched; AI provenance is recorded in rationale/limitations, never as pseudo
    evidence refs.
    """

    def __init__(
        self,
        *,
        provider: Any | None = None,
        model_name: str = DEEPSEEK_PREFILL_MODEL,
        prompt_version: str = PREFILL_AI_PROMPT_VERSION,
        timeout_seconds: float = DEEPSEEK_PREFILL_TIMEOUT_SECONDS,
        corpus_analysis_reader: Any | None = None,
        corpus_source_reader: Any | None = None,
    ) -> None:
        self._provider = provider
        self._model_name = model_name
        self._prompt_version = prompt_version
        self._timeout_seconds = timeout_seconds
        # Read-only ``(project_id, analysis_id) -> row dict | None`` lookup
        # for the round-1 corpus-analysis bridge.  When None and the journey
        # is bound to a round-1 analysis, the catalog build fails closed.
        self._corpus_analysis_reader = corpus_analysis_reader
        # Read-only ``(project_id, source_id, span_id) -> composite dict |
        # None`` lookup for source-binding integrity verification of the
        # round-1 analysis (artifact/span hashes, current-source state).
        self._corpus_source_reader = corpus_source_reader

    # ------------------------------------------------------------------
    # PrefillRankingAdapter protocol
    # ------------------------------------------------------------------

    def rank_and_phrase(
        self,
        *,
        field_path: str,
        candidates: list[AuthoringPrefillCandidate],
        context: dict[str, Any],
    ) -> list[AuthoringPrefillCandidate]:
        """Per-field ranking entry point (passthrough; bulk in enrich_package)."""
        ai_overrides = context.get("_ai_field_overrides", {})
        if field_path in ai_overrides:
            merged = _merge_ai_candidates(
                field_path=field_path,
                deterministic=candidates,
                ai_candidates=ai_overrides[field_path],
            )
            return merged
        return candidates

    # ------------------------------------------------------------------
    # Bulk enrichment (called outside the SQLite transaction)
    # ------------------------------------------------------------------

    def enrich_package(
        self,
        *,
        package: AuthoringPrefillPackage,
        state: MedicalWritingAuthoringJourney,
        snapshot: WritingReferenceSearchSnapshot | None = None,
        journey_revision: int | None = None,
    ) -> AuthoringPrefillPackage:
        """Run one bulk DeepSeek call and merge results into *package*.

        W2b-2 r2: Strict catalog-first path.  The evidence catalog is the
        sole evidence input.  No registered_source_ids, no snapshot_hints,
        no legacy field-suggestion bypass, no unbound condition term string.
        Every AI candidate must have at least one valid catalog binding;
        any binding failure rejects the entire candidate.

        ``journey_revision`` optionally overrides the revision the evidence
        catalog is built against.  The caller (``generate_prefill``) passes
        the next persisted journey revision so the persisted catalog and the
        live catalog rebuilt at adoption time carry the same identity.
        """
        if self._provider is None:
            return package.model_copy(
                update={
                    "partial_source_failures": list(package.partial_source_failures)
                    + ["authoring_prefill_ai: provider not configured"],
                    "model_name": package.model_name,
                    "prompt_version": package.prompt_version,
                },
                deep=True,
            )

        framing = state.framing
        product = framing.investigational_product.strip()
        indication = framing.indication.strip()
        phase = framing.study_phase.strip()
        existing_condition = framing.clinicaltrials_condition_term.strip()

        if not product or not indication or not phase:
            return package

        # W2b-2 r2: Build evidence catalog — sole evidence input.  The
        # read-only round-1 corpus-analysis bridge is injected so the
        # persisted, source-bound analysis reaches the model.
        catalog = build_evidence_catalog(
            state,
            snapshot=snapshot,
            corpus_analysis_reader=self._corpus_analysis_reader,
            corpus_source_reader=self._corpus_source_reader,
            journey_revision=journey_revision,
        )

        # W2b-2 r3: Extract server package target paths — fail-closed.
        try:
            package_target_paths = _extract_package_target_paths(package)
        except PackageTargetPathError as exc:
            return _mark_partial_failure(
                package,
                f"authoring_prefill_ai: server package target paths error: {exc}",
            )

        deterministic_field_paths = set(package.field_candidates.keys())
        catalog_projection = project_catalog_for_model(
            catalog,
            deterministic_field_paths=deterministic_field_paths,
            package_target_paths=package_target_paths,
        )

        request_payload = _build_bulk_request(
            product=product,
            indication=indication,
            phase=phase,
            existing_condition=existing_condition,
            field_candidates=package.field_candidates,
            catalog_projection=catalog_projection,
        )

        # Hard payload size check.
        payload_str = json.dumps(request_payload, ensure_ascii=False)
        if len(payload_str) > MAX_TOTAL_PAYLOAD_CHARS:
            return _mark_partial_failure(
                package,
                f"authoring_prefill_ai: payload exceeds hard limit "
                f"({len(payload_str)} > {MAX_TOTAL_PAYLOAD_CHARS} chars)",
            )

        try:
            raw_response = self._call_provider(request_payload)
        except Exception as exc:
            _diag = getattr(exc, "diagnostics", None)
            logger.warning(
                "authoring prefill AI call failed: %s | diagnostics: %s",
                exc,
                json.dumps(_diag, ensure_ascii=False, default=str)
                if _diag
                else "none",
            )
            return _mark_partial_failure(
                package,
                f"authoring_prefill_ai: provider call failed: "
                f"{type(exc).__name__}: {exc}",
            )

        effective_model_name = str(
            getattr(self._provider, "model_name", "") or self._model_name
        )
        run_audit = _build_prefill_ai_run_audit(
            provider=self._provider,
            model_name=effective_model_name,
            prompt_version=self._prompt_version,
            request_payload=request_payload,
            raw_response=raw_response,
        )

        ai_result = _extract_prefill_suggestions(raw_response)
        if not isinstance(ai_result, dict):
            raw_keys = (
                ",".join(sorted(str(key) for key in raw_response.keys()))
                if isinstance(raw_response, dict)
                else type(raw_response).__name__
            )
            return _mark_partial_failure(
                package,
                "authoring_prefill_ai: response does not match the bulk prefill schema"
                f" (top_level={raw_keys[:300]})",
            )

        # The response is synchronously bound to this exact server-built
        # catalog. Some OpenAI-compatible models omit copied metadata even
        # when their candidate bindings are otherwise valid. Bind only
        # missing identity fields from the request context; never overwrite a
        # mismatched value returned by the model. Every claim_binding remains
        # constrained to sent_entry_ids and is rebound server-side.
        if not str(ai_result.get("catalog_id", "")).strip():
            ai_result = dict(ai_result)
            ai_result["catalog_id"] = catalog.catalog_id
        if not str(ai_result.get("catalog_sha256", "")).strip():
            ai_result = dict(ai_result)
            ai_result["catalog_sha256"] = catalog.catalog_sha256

        # W2b-2 r2: Validate ALL output against the server-side catalog.
        sent_entry_ids = set(catalog_projection["sent_entry_ids"])
        (
            condition_candidate,
            field_candidates_list,
            package_candidates_dict,
            all_validated_candidates,
            validation_errors,
        ) = validate_and_rebind_candidates(
            catalog=catalog,
            sent_entry_ids=sent_entry_ids,
            model_output=ai_result,
            condition_term_path=_CONDITION_TERM_PATH,
            eligible_field_paths=set(_AI_ELIGIBLE_FIELDS),
            package_target_paths=package_target_paths,
        )

        # A model may legitimately omit eligible evidence.  Verified round-1
        # Protocol observations must nevertheless remain visible as bounded,
        # review-only competitor options.  Deterministic extraction is routed
        # through the exact same binding validator; it cannot create current
        # facts or exact-fact values.
        corpus_review_candidates, corpus_review_errors = (
            build_round1_corpus_review_candidates(
                catalog=catalog,
                sent_entry_ids=sent_entry_ids,
                package_target_paths=package_target_paths,
            )
        )
        if corpus_review_candidates:
            all_validated_candidates.setdefault(
                "package.design", []
            ).extend(corpus_review_candidates)
        validation_errors.extend(corpus_review_errors)

        # Apply language/evidence quality gate to every validated candidate.
        field_overrides: dict[str, list[AuthoringPrefillCandidate]] = {}
        for field_path, cand_list in all_validated_candidates.items():
            gated = []
            for ai_cand in cand_list:
                passed, reason, gap_notes = _passes_language_and_evidence_gate(
                    field_path,
                    ai_cand.structured_value,
                    ai_cand.preview,
                    ai_cand.rationale,
                    evidence_refs=ai_cand.evidence_refs,
                    claim_bindings=ai_cand.claim_bindings,
                    evidence_status=ai_cand.evidence_status,
                )
                if not passed:
                    if gap_notes:
                        # Unsupported substantive claim: keep the candidate
                        # visible with its gap, demoted and non-adoptable.
                        gated.append(
                            _surface_unsupported_substantive_gap(
                                ai_cand, gap_notes
                            ).model_copy(
                                update={"ai_run_id": run_audit.ai_run_id}
                            )
                        )
                        continue
                    logger.info(
                        "W2b candidate %s rejected by quality gate: %s",
                        field_path, reason,
                    )
                    validation_errors.append(
                        f"quality_gate_rejected: {field_path}: {reason}"
                    )
                    continue
                gated.append(
                    ai_cand.model_copy(update={"ai_run_id": run_audit.ai_run_id})
                )
            if gated:
                field_overrides[field_path] = gated

        # Condition term candidate (catalog-bound only).
        if condition_candidate is not None:
            passed, reason, gap_notes = _passes_language_and_evidence_gate(
                _CONDITION_TERM_PATH,
                condition_candidate.structured_value,
                condition_candidate.preview,
                condition_candidate.rationale,
                evidence_refs=condition_candidate.evidence_refs,
                claim_bindings=condition_candidate.claim_bindings,
                evidence_status=condition_candidate.evidence_status,
            )
            if passed:
                field_overrides[_CONDITION_TERM_PATH] = [
                    condition_candidate.model_copy(
                        update={"ai_run_id": run_audit.ai_run_id}
                    )
                ]
            elif gap_notes:
                field_overrides[_CONDITION_TERM_PATH] = [
                    _surface_unsupported_substantive_gap(
                        condition_candidate, gap_notes
                    ).model_copy(
                        update={"ai_run_id": run_audit.ai_run_id}
                    )
                ]
            else:
                validation_errors.append(
                    f"quality_gate_rejected: {_CONDITION_TERM_PATH}: {reason}"
                )

        if not field_overrides:
            extra_failures = []
            if validation_errors:
                extra_failures.append(
                    "authoring_prefill_ai: "
                    + "; ".join(validation_errors[:5])
                )
            return package.model_copy(
                update={
                    **run_audit.as_package_update(),
                    "model_name": effective_model_name,
                    "prompt_version": self._prompt_version,
                    "partial_source_failures": (
                        list(package.partial_source_failures) + extra_failures
                    ),
                },
                deep=True,
            )

        new_field_candidates: dict[str, AuthoringPrefillFieldCandidates] = {}
        for field_path, group in package.field_candidates.items():
            deterministic = list(group.candidates)
            ai_candidates = field_overrides.get(field_path, [])
            if ai_candidates:
                merged = _merge_ai_candidates(
                    field_path=field_path,
                    deterministic=deterministic,
                    ai_candidates=ai_candidates,
                )
                if merged:
                    distinct = dedupe_materially_distinct(merged, max_alternatives=4)
                    if distinct:
                        new_field_candidates[field_path] = AuthoringPrefillFieldCandidates(
                            field_path=field_path,
                            recommended_candidate_id=(
                                _recommended_candidate_id_for_group(distinct)
                            ),
                            candidates=distinct,
                        )
                        continue
            new_field_candidates[field_path] = group

        for field_path, ai_candidates in field_overrides.items():
            if field_path in new_field_candidates:
                continue
            distinct = dedupe_materially_distinct(ai_candidates, max_alternatives=4)
            if distinct:
                new_field_candidates[field_path] = AuthoringPrefillFieldCandidates(
                    field_path=field_path,
                    recommended_candidate_id=(
                        _recommended_candidate_id_for_group(distinct)
                    ),
                    candidates=distinct,
                )

        partial_failures = list(package.partial_source_failures)
        if validation_errors:
            validated_count = sum(len(items) for items in field_overrides.values())
            surfaced_count = sum(
                1
                for group in new_field_candidates.values()
                for candidate in group.candidates
                if candidate.ai_run_id == run_audit.ai_run_id
            )
            partial_failures.append(
                "authoring_prefill_ai: "
                f"validated {validated_count} evidence-bound candidate(s); "
                f"surfaced {surfaced_count} selectable candidate(s); "
                f"rejected {len(validation_errors)} invalid candidate/binding item(s): "
                + "; ".join(validation_errors[:3])
            )

        return package.model_copy(
            update={
                **run_audit.as_package_update(),
                "field_candidates": new_field_candidates,
                "model_name": effective_model_name,
                "prompt_version": self._prompt_version,
                "evidence_catalog": catalog,
                "partial_source_failures": partial_failures,
            },
            deep=True,
        )

    # ------------------------------------------------------------------
    # Provider call — D5: no synthesized model identity
    # ------------------------------------------------------------------

    def _call_provider(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        """Issue one structured DeepSeek chat completion request.

        D5: Model identity is NOT synthesized.  For the configured
        concrete ``OpenAICompatibleAiProvider`` (which does strict HTTP response
        identity validation and raises ``AiProviderRuntimeError`` on mismatch),
        the adapter trusts the completed call — no extra key is injected. For
        generic injected providers, an explicit exact ``_response_model`` key
        is required in the returned dict; missing or mismatched identity raises
        ``RuntimeError`` to trigger deterministic fallback.
        """
        provider = self._provider
        if provider is None:
            raise RuntimeError("provider is not configured")

        if hasattr(provider, "run"):
            # Fail closed BEFORE any transport attempt: this route is
            # contractually single-attempt.  A provider built with the
            # generic retry budget must never be used here (worker_02
            # corrective round).
            from .ai_gateway import OpenAICompatibleAiProvider
            from .ai_runtime_fallback_provider import RuntimeFallbackAiProvider

            if isinstance(
                provider, (OpenAICompatibleAiProvider, RuntimeFallbackAiProvider)
            ):
                if provider.max_attempts != 1:
                    raise RuntimeError(
                        "authoring_prefill_ai requires exactly one physical "
                        "transport attempt per logical call; provider is "
                        f"configured with max_attempts={provider.max_attempts}"
                    )
            envelope = _BulkPrefillEnvelope(
                system_prompt=_BULK_SYSTEM_PROMPT,
                payload=request_payload,
            )
            result = provider.run(envelope)
            if not isinstance(result, dict):
                raise RuntimeError("provider returned non-dict result")

            # D5: Only the concrete production provider may assert that model
            # identity was already verified from the HTTP response. A generic
            # provider must not gain that trust merely by exposing a similarly
            # named attribute.
            if isinstance(
                provider, (OpenAICompatibleAiProvider, RuntimeFallbackAiProvider)
            ):
                # The provider already compares the upstream response with
                # its frozen expected_response_model.  The configured request
                # alias may intentionally differ from that calibrated served
                # identity (for example deepseek-flash ->
                # deepseek-latest-cloud), so repeating an alias comparison
                # here would reject a response that has already passed the
                # authoritative transport contract.
                return result

            # D5: For generic injected providers, require explicit exact
            # _response_model in the result dict.
            returned_model = str(result.get("_response_model", "")).strip()
            if not returned_model:
                raise RuntimeError(
                    "generic provider did not return _response_model; "
                    "cannot verify model identity"
                )
            if returned_model != self._model_name:
                raise RuntimeError(
                    f"model identity mismatch: expected {self._model_name}, "
                    f"got {returned_model}"
                )
            return result

        raise RuntimeError(
            f"provider {type(provider).__name__} has no compatible call interface"
        )


# ---------------------------------------------------------------------------
# Bulk request / response helpers
# ---------------------------------------------------------------------------

class PackageTargetPathError(Exception):
    """Raised when deterministic package target paths cannot be extracted."""


def _extract_package_target_paths(
    package: AuthoringPrefillPackage,
) -> dict[str, list[str]]:
    """Extract target_paths from the four PICOS package candidates.

    Fail-closed: every one of the four PACKAGE_KEYS must be present in
    the package, have at least one candidate, the candidate must be
    module/design_package scope with non-empty target_paths, and all
    candidates within the same group must have the same target_paths set.

    Raises PackageTargetPathError on any violation.
    """
    result: dict[str, list[str]] = {}
    for pkg_key in PACKAGE_KEYS:
        group = package.field_candidates.get(pkg_key)
        if group is None:
            raise PackageTargetPathError(
                f"package group '{pkg_key}' is missing from deterministic package"
            )
        if not group.candidates:
            raise PackageTargetPathError(
                f"package group '{pkg_key}' has no candidates"
            )
        # Validate EVERY candidate in the group — not just the first.
        first_tp_set = set(group.candidates[0].target_paths)
        if not first_tp_set:
            raise PackageTargetPathError(
                f"package group '{pkg_key}' first candidate has empty target_paths"
            )
        for cand_idx, cand in enumerate(group.candidates):
            if cand.candidate_scope not in ("module", "design_package"):
                raise PackageTargetPathError(
                    f"package group '{pkg_key}' candidate[{cand_idx}] scope is "
                    f"'{cand.candidate_scope}', expected module/design_package"
                )
            if not cand.target_paths:
                raise PackageTargetPathError(
                    f"package group '{pkg_key}' candidate[{cand_idx}] has empty target_paths"
                )
            if set(cand.target_paths) != first_tp_set:
                raise PackageTargetPathError(
                    f"package group '{pkg_key}' has inconsistent target_paths "
                    f"across candidates: {sorted(first_tp_set)} vs "
                    f"{sorted(set(cand.target_paths))}"
                )
        result[pkg_key] = sorted(first_tp_set)
    return result


_BULK_SYSTEM_PROMPT = (
    "你是中国临床试验方案撰写工作台的预填候选助手。你会收到已确认的研究创建"
    "最小信息（试验药物、适应症、研究分期）、当前的确定性预填候选和一份证据"
    "目录（evidence_catalog）。\n\n"
    "你的任务：\n"
    "1. 为给定适应症提出一个医学准确的英文 ClinicalTrials.gov 疾病检索词"
    "（clinicaltrials_condition_term_en）。该词仅用于注册库检索，是候选而非确认值。\n"
    "2. 基于证据目录，为支持的 framing.*、picos.* 和正交 design.* 字段提供"
    "3–5个实质不同、可直接选择后精调的规范中文候选。\n"
    "3. 为请求中列出的组合包提供3–5个结构化候选；候选应覆盖推荐方案、"
    "保守备选和适用场景不同的备选，避免同义改写凑数。组合包键仅可为"
    "package.population、package.intervention、package.outcomes、"
    "package.statistics、package.design、package.product。\n\n"
    "严格规则：\n"
    "- clinicaltrials_condition_term_en 必须为英文，适合 ClinicalTrials.gov "
    "query.cond 检索。除此之外，所有候选的 value、preview、rationale 必须使用"
    "适合中国临床试验方案的规范中文。\n"
    "- 研究设计、人群、给药途径、治疗线、严重程度、靶点/机制等不得仅凭药物"
    "代号、适应症或分期推断。只有存在与目标字段兼容的 claim_bindings 时，才可"
    "作为『AI候选方案』提出；它们不是当前研究事实，须在 rationale 中说明依据，"
    "在 evidence_gaps 中说明仍需项目确认的差异。\n"
    "- competitor_observation 只能支持竞品设计选项或适应症惯例分析，不能表述为"
    "当前研究已确定。推荐候选优先综合至少2个不同研究/申办方；若仅有单一来源，"
    "应降低推荐强度并明确样本局限。不得把跨适应症通用模板冒充本适应症惯例。\n"
    "- 先识别适应症、分期、药物技术类型/给药途径和研究目的的适用层级，再综合"
    "同适应症同分期证据；跨适应症语料仅用于结构或监管措辞，不得直接迁移疾病"
    "活动度、终点、背景治疗、洗脱、风险或访视逻辑。\n"
    "- 不得虚构精确临床事实：不得写入剂量/频次/给药间隔/主要或关键次要终点/"
    "AESI/样本量/洗脱期/数值阈值/访视时间窗（这些已被系统阻断）。\n"
    "- 你只能引用 evidence_catalog.sent_entry_ids 中列出的目录条目ID。"
    "每条候选必须包含 claim_bindings，其中 catalog_entry_id 必须来自已发送的"
    "条目集合。source/locator/quote_sha256 由服务端从目录条目回绑，模型回显"
    "这些字段将被忽略。\n"
    "- 对每个 claim_binding，catalog_entry_id 还必须出现在 "
    "evidence_catalog.eligible_entry_ids_by_target_path[target_path] 中。"
    "如果某目标字段没有对应条目ID，必须省略该字段或组合包候选，不能用适应症、"
    "药物代号、标题或其他邻近信息代替该字段的直接证据。\n"
    "- 证据目录中 support_scope=competitor_observation 的条目只能作为"
    "competitor_option 设计参照，不等于当前研究已确认的事实；相同表述在不同"
    "适应症中的使用习惯不一致时，按本适应症证据分别总结，不强行统一措辞。\n"
    "- claim_bindings[].support_kind 只能逐字填写 competitor_option、exact_fact"
    "或 normalized_enum；support_scope=competitor_observation 绝不能回显为"
    "support_kind=competitor_observation。\n"
    "- 证据目录中 support_scope=current_project_fact 的条目可支持对应"
    "supported_target_paths 中的字段作为 exact_fact 或 normalized_enum。\n"
    "- 药物代号（如 CMS-D017）、NCT 编号、PK/PD、SAD/MAD、PNH 等必要英文"
    "缩写可保留，但候选正文不得为整句英文。\n"
    "- 每个候选必须附简短中文 rationale。\n"
    "- 组合包候选的 target_paths 必须与 evidence_catalog.package_target_paths "
    "完全一致。每个 claim_binding 的 value_pointer 必须为 RFC6901 格式"
    "（如 /picos.population_summary 或 /picos.inclusion_modules/0），指向"
    "structured_value 中对应 target_path 下的非空原子叶值。组合包内每一个"
    "非空原子叶值都必须各自具有直接 claim_binding；没有直接证据的 target_path "
    "必须保留为空值，不得用“待确认”包装无证据内容。\n"
    "- recommendation_role 只能为 recommended、alternative 或 "
    "pending_decision，不能输出 conservative 等其他值。\n"
    "- 必须在输出中回显 evidence_catalog.catalog_id 和 "
    "evidence_catalog.catalog_sha256。\n"
    "- 顶层对象必须且只能包含 clinicaltrials_condition_term_en、"
    "field_suggestions、package_suggestions、catalog_id、catalog_sha256。"
    "严禁把单个候选对象直接作为顶层输出；即使没有可支持候选，也必须返回上述"
    "完整顶层对象，并将相应 suggestions 设为空对象。\n"
    "- 只返回符合请求 schema 的 JSON 对象。\n"
)


def _build_bulk_request(
    *,
    product: str,
    indication: str,
    phase: str,
    existing_condition: str,
    field_candidates: dict[str, AuthoringPrefillFieldCandidates],
    catalog_projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the structured payload for the bulk DeepSeek request.

    W2b-2 r2: The evidence catalog is the sole evidence input.  No
    registered_source_ids, no snapshot_hints.  The model receives catalog
    entries with catalog_entry_id/source/locator/quote_sha256 and must
    return claim_bindings referencing sent entry IDs; the server rebinds
    all source/locator/quote data from authoritative entries.
    """
    compact_candidates: list[dict[str, Any]] = []
    for field_path, group in field_candidates.items():
        if field_path not in _AI_ELIGIBLE_FIELDS:
            continue
        if field_path in EXACT_FACT_PATHS:
            continue
        for cand in group.candidates:
            compact_candidates.append(
                {
                    "field_path": field_path,
                    "value": cand.structured_value,
                    "preview": cand.preview,
                    "confidence": cand.confidence,
                }
            )

    payload: dict[str, Any] = {
        "task_type": "authoring_prefill_bulk",
        "prompt_version": PREFILL_AI_PROMPT_VERSION,
        "study_creation_minimum": {
            "investigational_product": product,
            "indication": indication,
            "study_phase": phase,
        },
        "existing_clinicaltrials_condition_term": existing_condition,
        "current_deterministic_candidates": compact_candidates,
        "output_schema": {
            "clinicaltrials_condition_term_en": (
                "string; a medically correct English condition term suitable "
                "for ClinicalTrials.gov query.cond. Empty string if uncertain."
            ),
            "field_suggestions": (
                "object mapping supported field_path to arrays of candidate "
                "objects, each with {structured_value, preview (Chinese), "
                "rationale (Chinese), recommendation_role, clinical_tradeoffs, "
                "evidence_gaps, claim_bindings (array of {target_path, "
                "value_pointer (empty for field), catalog_entry_id, "
                "support_kind})}. Every candidate MUST have at least one "
                "valid claim_binding. Only catalog_entry_ids from "
                "evidence_catalog.sent_entry_ids are valid."
            ),
            "package_suggestions": (
                "object mapping one of [package.population, "
                "package.intervention, package.outcomes, package.statistics, "
                "package.design, package.product] "
                "to arrays of candidate objects, each with: target_paths "
                "(MUST exactly match evidence_catalog.package_target_paths[key]), "
                "structured_value (object keyed by those target_paths), "
                "preview (Chinese), rationale (Chinese), "
                "recommendation_role (one of recommended, alternative, "
                "pending_decision), clinical_tradeoffs, evidence_gaps, "
                "claim_bindings (array of {target_path, value_pointer "
                "(RFC6901 pointer into structured_value), catalog_entry_id, "
                "support_kind}). Every candidate MUST have at least one "
                "valid claim_binding. source/locator/quote_sha256 are "
                "server-rebound."
            ),
            "catalog_id": "MUST echo evidence_catalog.catalog_id",
            "catalog_sha256": "MUST echo evidence_catalog.catalog_sha256",
        },
        "supported_field_paths": sorted(_AI_ELIGIBLE_FIELDS),
        "exact_fact_blocked_paths": sorted(EXACT_FACT_PATHS),
    }
    # W2b-2 r2: catalog_projection is the sole evidence input.
    if catalog_projection is not None:
        payload["evidence_catalog"] = catalog_projection
        payload["response_contract_reminder"] = {
            "instruction": (
                "Return this complete top-level object. Never return a single "
                "candidate object as the top-level response."
            ),
            "required_top_level_keys": [
                "clinicaltrials_condition_term_en",
                "field_suggestions",
                "package_suggestions",
                "catalog_id",
                "catalog_sha256",
            ],
            "template": {
                "clinicaltrials_condition_term_en": "",
                "field_suggestions": {},
                "package_suggestions": {},
                "catalog_id": catalog_projection["catalog_id"],
                "catalog_sha256": catalog_projection["catalog_sha256"],
            },
        }
    return payload


def _extract_prefill_suggestions(raw_response: Any) -> dict[str, Any] | None:
    """Normalize the production response to the documented bulk schema.

    The prompt's ``output_schema`` describes a direct JSON object with
    ``clinicaltrials_condition_term_en`` and ``field_suggestions`` at the top
    level.  Early test adapters wrapped that object in ``prefill_suggestions``;
    retain that legacy shape only for compatibility while making the direct
    production shape authoritative.
    """
    def _walk(payload: Any, depth: int = 0) -> dict[str, Any] | None:
        if not isinstance(payload, dict) or depth > 2:
            return None
        if any(
            key in payload
            for key in ("clinicaltrials_condition_term_en", "field_suggestions")
        ):
            return payload
        # Some OpenAI-compatible gateways wrap the model's JSON once more in
        # ``output``/``result``/``data``.  Keep this normalization narrow and
        # bounded; the normal server-side catalog/binding validators remain
        # authoritative after extraction.
        for wrapper in ("prefill_suggestions", "output", "result", "data", "response"):
            nested = payload.get(wrapper)
            if isinstance(nested, str):
                try:
                    nested = json.loads(nested)
                except json.JSONDecodeError:
                    continue
            extracted = _walk(nested, depth + 1)
            if extracted is not None:
                return extracted

        # DeepSeek may also serialize the field map itself as the top-level
        # object when the requested package groups have no directly bindable
        # evidence.  Accept only the exact server allowlist and list-shaped
        # suggestion values; downstream catalog/binding validation still
        # decides which candidates can be surfaced or adopted.
        if payload and all(
            key in _AI_ELIGIBLE_FIELDS and isinstance(value, list)
            for key, value in payload.items()
        ):
            return {
                "clinicaltrials_condition_term_en": "",
                "field_suggestions": payload,
                "package_suggestions": {},
            }
        return None

    return _walk(raw_response)


def _parse_field_suggestions(
    field_path: str,
    suggestions: list[Any],
    *,
    registered_source_ids: frozenset[str],
) -> list[AuthoringPrefillCandidate]:
    """Parse AI field suggestions into validated candidates.

    D1: AI candidates carry no pseudo-source evidence refs.  Provenance is
    recorded in rationale and limitations.
    D2: exact-fact content requires a cited registered source ID; that real ID
    becomes the evidence ref.  Non-exact candidates have no evidence refs
    (rationale/limitations carry the provenance).
    """
    result: list[AuthoringPrefillCandidate] = []
    for index, item in enumerate(suggestions[:4]):
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        preview = item.get("preview") or ""
        rationale = item.get("rationale") or ""
        if value is None:
            continue
        if not isinstance(value, str) and not isinstance(value, (list, dict)):
            value = str(value)
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
            preview = (preview or value).strip()
        else:
            preview = (preview or str(value)).strip()
        if not preview:
            continue

        combined_text = f"{value} {preview} {rationale}"
        exact_category = _detect_exact_fact_content(combined_text)

        evidence_refs: list[AuthoringPrefillEvidenceRef] = []

        if exact_category is not None:
            # D2: require a cited registered source ID.
            cited_ids = _extract_cited_source_ids(item)
            registered_cited = _filter_registered_ids(cited_ids, registered_source_ids)
            if not registered_cited:
                logger.info(
                    "quarantining AI candidate for %s: detected %s pattern "
                    "without registered source evidence",
                    field_path,
                    exact_category,
                )
                continue
            # D2: attach the real registered source ID(s) as evidence refs.
            for sid in registered_cited[:5]:
                evidence_refs.append(
                    AuthoringPrefillEvidenceRef(
                        source_kind="study_definition",
                        source_id=sid,
                        source_text="",
                        locator=field_path,
                    )
                )
        # D1: non-exact candidates get NO evidence refs — AI provenance lives
        # in rationale/limitations, not in pseudo-source evidence.

        digest = payload_sha256(
            {"field_path": field_path, "value": value, "suffix": f"ai-{index}"}
        )[:16]
        candidate = AuthoringPrefillCandidate(
            candidate_id=f"mwprefillai_{digest}",
            field_path=field_path,
            structured_value=value,
            preview=preview[:5000],
            evidence_refs=evidence_refs,
            rationale=str(rationale)[:5000] or "AI提出的候选建议",
            limitations=[
                "AI预填候选，需由医学经理核对后采用。",
            ],
            confidence="medium",
            state="ai_proposed",
        )
        result.append(candidate)
    return result


def _build_condition_candidate(
    condition_term: str,
    *,
    indication: str,
    phase: str,
) -> AuthoringPrefillCandidate | None:
    """Build an English ClinicalTrials.gov condition term candidate.

    D1: The only evidence ref is the real ``framing.indication`` input — the
    original indication string is the source text.  No pseudo-source.  AI
    provenance is recorded in rationale and limitations.
    """
    if not condition_term:
        return None
    digest = payload_sha256(
        {
            "field_path": _CONDITION_TERM_PATH,
            "value": condition_term,
            "suffix": "ai-condition",
        }
    )[:16]
    return AuthoringPrefillCandidate(
        candidate_id=f"mwprefillai_{digest}",
        field_path=_CONDITION_TERM_PATH,
        structured_value=condition_term,
        preview=condition_term,
        evidence_refs=[
            # D1: only the real framing.indication input as evidence.
            # source_text is the original indication, NOT the AI output.
            AuthoringPrefillEvidenceRef(
                source_kind="study_definition",
                source_id="framing.indication",
                source_text=indication,
                locator="framing.indication",
            ),
        ],
        rationale=(
            f"AI为{indication}（{phase}）提出的英文 ClinicalTrials.gov "
            f"疾病检索词候选，需医学经理确认后方可用于注册库检索。"
        ),
        limitations=[
            "AI提出的检索词候选，医学经理确认后方可用于注册库检索。",
        ],
        confidence="medium",
        state="ai_proposed",
    )


def _merge_ai_candidates(
    *,
    field_path: str,
    deterministic: list[AuthoringPrefillCandidate],
    ai_candidates: list[AuthoringPrefillCandidate],
) -> list[AuthoringPrefillCandidate]:
    """Merge AI candidates with deterministic candidates.

    Quality-gate rules (fail-closed):
    - The language+evidence gate is applied to every AI candidate.
    - Candidates that fail the gate without a substantive evidence gap are
      **dropped entirely** — they must never appear as selectable
      candidates, not even as non-recommended alternatives.
    - Candidates whose substantive claim is absent from every bound quote
      (``gap_notes`` non-empty) stay visible as manual-only alternatives
      carrying the reader-facing gap; they are demoted and ranked after
      clean evidence-bound candidates so they never occupy the recommended
      slot.
    - Condition-term path is exempt from the language gate.

    Ranking rules:
    - Candidates with real source evidence rank highest.
    - Deterministic candidates with evidence rank above pure-AI candidates
      that lack new verifiable evidence.
    - Pure rephrasing candidates without evidence may appear as alternatives
      but must not displace evidence-bound candidates from recommendation.
    - Dedup by canonical value; cap at 5 (1 recommended + 4 alternatives).
    """
    if not ai_candidates:
        return deterministic

    existing_canonical = {
        canonicalize_candidate_value(c.structured_value) for c in deterministic
    }

    # Apply quality gate to each AI candidate; hard-drop failures.
    gated_ai: list[AuthoringPrefillCandidate] = []
    for ai_cand in ai_candidates:
        canon = canonicalize_candidate_value(ai_cand.structured_value)
        if canon in existing_canonical:
            continue
        passed, reason, gap_notes = _passes_language_and_evidence_gate(
            field_path,
            ai_cand.structured_value,
            ai_cand.preview,
            ai_cand.rationale,
            evidence_refs=ai_cand.evidence_refs,
            claim_bindings=ai_cand.claim_bindings,
            evidence_status=ai_cand.evidence_status,
        )
        if not passed:
            if gap_notes:
                gated_ai.append(
                    _surface_unsupported_substantive_gap(ai_cand, gap_notes)
                )
                continue
            logger.info(
                "语言/证据质量门拒绝AI候选 %s: %s",
                field_path,
                reason,
            )
            continue
        gated_ai.append(ai_cand)

    if not gated_ai:
        return deterministic

    # Partition by evidence status.  Candidates with an unsupported
    # substantive gap rank after clean evidence-bound candidates so they
    # can never become the first (recommended) element of the group.
    ai_gap = [c for c in gated_ai if _has_unsupported_substantive_gap(c)]
    clean_ai = [c for c in gated_ai if not _has_unsupported_substantive_gap(c)]
    ai_with_evidence = [c for c in clean_ai if _has_real_evidence(c)]
    ai_without_evidence = [c for c in clean_ai if not _has_real_evidence(c)]
    det_with_evidence = [c for c in deterministic if _has_real_evidence(c)]
    det_without_evidence = [c for c in deterministic if not _has_real_evidence(c)]

    merged: list[AuthoringPrefillCandidate] = []
    seen_canonical: set[str] = set()

    def _add_unique(candidates: list[AuthoringPrefillCandidate]) -> None:
        for cand in candidates:
            canon = canonicalize_candidate_value(cand.structured_value)
            if canon in seen_canonical:
                continue
            seen_canonical.add(canon)
            merged.append(cand)

    # Priority order:
    # 1. AI candidates with real evidence (new verifiable evidence)
    # 2. Deterministic candidates with evidence
    # 3. AI candidates with an unsupported-substantive gap (visible, demoted)
    # 4. AI candidates without evidence (rephrasing only)
    # 5. Deterministic candidates without evidence
    _add_unique(ai_with_evidence)
    _add_unique(det_with_evidence)
    _add_unique(ai_gap)
    _add_unique(ai_without_evidence)
    _add_unique(det_without_evidence)

    return merged[:5]


def _mark_partial_failure(
    package: AuthoringPrefillPackage,
    reason: str,
) -> AuthoringPrefillPackage:
    """Return a copy of *package* with a partial_source_failures entry."""
    failures = list(package.partial_source_failures)
    if reason not in failures:
        failures.append(reason)
    return package.model_copy(
        update={"partial_source_failures": failures},
        deep=True,
    )


# ---------------------------------------------------------------------------
# Minimal envelope shim for the AiProvider protocol
# ---------------------------------------------------------------------------


class _BulkPrefillEnvelope:
    """Lightweight envelope compatible with AiProvider.run()."""

    task_id = "authoring_prefill_bulk"
    task_type = None  # type: ignore[assignment]
    prompt_version = PREFILL_AI_PROMPT_VERSION

    def __init__(self, system_prompt: str, payload: dict[str, Any]) -> None:
        self.system_prompt = system_prompt
        self.payload = payload
        self.thinking = None
        # This route is pinned to the independent-AI binding: DeepSeek V4
        # Flash with the user's maximum reasoning setting.  Keep the envelope
        # explicit so a provider profile cannot silently downgrade the role.
        self.reasoning_effort = "max"
        # DeepSeek-V4 thinking tokens and the visible JSON share
        # ``max_tokens``.  At the required ``max`` reasoning effort a 16K
        # ceiling can be consumed entirely by reasoning, yielding the
        # provider's documented empty-content/finish_reason=length response
        # and no structured candidate payload.  Keep the role at max while
        # giving the bounded prefill response enough headroom for reasoning
        # plus its evidence-bound JSON; 64K remains within the model's
        # documented output ceiling (the earlier 16K/32K ceilings were both
        # consumed entirely by max-effort reasoning over large corpus contexts).
        self.max_output_tokens = 65536


def _resolve_prefill_timeout_seconds(
    provider: Any,
    provider_env: Mapping[str, str] | None,
) -> float:
    """Resolve one auditable timeout for the dedicated prefill transport.

    The ordinary role profile timeout remains unchanged for other AI tasks.
    Prefill may use an explicit route override, otherwise it raises a short
    generic profile budget to the safe max-reasoning floor.  The provider
    object is updated as well as the adapter so urllib and the local wait
    boundary cannot disagree and create a premature ``unknown_outcome``.
    """
    values = dict(provider_env) if provider_env is not None else dict(os.environ)
    configured = float(getattr(provider, "timeout_seconds", 300.0))
    raw_override = str(values.get("WORKBENCH_AI_PREFILL_TIMEOUT_SECONDS", "")).strip()
    if raw_override:
        try:
            configured = float(raw_override)
        except (TypeError, ValueError):
            logger.warning(
                "authoring_prefill_ai: invalid WORKBENCH_AI_PREFILL_TIMEOUT_SECONDS=%r; using safe default",
                raw_override,
            )
            configured = DEEPSEEK_PREFILL_TIMEOUT_SECONDS
    # Match the provider-profile schema bounds and prevent a zero/negative
    # override from silently disabling the route.  If the stored profile is
    # already larger than the safe default, preserve that operator choice.
    timeout_seconds = max(60.0, min(1800.0, configured))
    if not raw_override:
        timeout_seconds = max(
            timeout_seconds,
            DEEPSEEK_PREFILL_TIMEOUT_SECONDS,
        )
    if hasattr(provider, "timeout_seconds"):
        provider.timeout_seconds = timeout_seconds
    return timeout_seconds


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_prefill_ai_adapter(
    corpus_analysis_reader: Any | None = None,
    corpus_source_reader: Any | None = None,
    provider_env: Mapping[str, str] | None = None,
    provider: Any | None = None,
) -> DeepSeekPrefillAdapter | None:
    """Build the product prefill adapter from the active independent-AI route.

    ``corpus_analysis_reader`` is the read-only round-1 corpus-analysis
    lookup and ``corpus_source_reader`` the read-only span/artifact
    composite lookup injected into the evidence catalog build.
    """
    from .ai_gateway import (
        DisabledAiProvider,
        configured_ai_provider_from_env,
    )

    # The AI-first prefill route is restricted to at most one physical
    # upstream POST per logical call (worker_02 corrective round): the
    # provider is built with a single-attempt transport while every other
    # AI gateway caller keeps the generic bounded retry budget.
    if provider is None:
        provider = configured_ai_provider_from_env(
            dict(provider_env) if provider_env is not None else None,
            max_attempts=1,
        )
    if isinstance(provider, DisabledAiProvider) or not hasattr(provider, "run"):
        return None
    model_name = getattr(provider, "model_name", "")
    if not model_name:
        return None
    timeout_seconds = _resolve_prefill_timeout_seconds(provider, provider_env)
    return DeepSeekPrefillAdapter(
        provider=provider,
        model_name=model_name,
        timeout_seconds=timeout_seconds,
        corpus_analysis_reader=corpus_analysis_reader,
        corpus_source_reader=corpus_source_reader,
    )


def build_deepseek_prefill_adapter(
    corpus_analysis_reader: Any | None = None,
    corpus_source_reader: Any | None = None,
    provider_env: Mapping[str, str] | None = None,
) -> DeepSeekPrefillAdapter | None:
    """Backward-compatible alias for the provider-neutral product factory."""

    return build_prefill_ai_adapter(
        corpus_analysis_reader=corpus_analysis_reader,
        corpus_source_reader=corpus_source_reader,
        provider_env=provider_env,
    )
