"""Project-level medical-writing full-draft candidate workflow.

The full draft is deliberately separate from the paragraph revision thread:
it is a bounded, source-bound AI candidate artifact.  Generation never mutates
working copies; explicit adoption performs per-section CAS saves with stable
idempotency keys.  The durable job row stores only a locator and digest while
the candidate JSON remains in the runtime artifact directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, get_args, get_origin

from packages.contracts.workbench_contracts import (
    AiTaskRequest,
    AiTaskRunStatus,
    AiTaskSourceRef,
    DurableJobCreateRequest,
    DurableJobProgressPayload,
    MedicalWritingPicosDefinition,
    MedicalWritingStudyFraming,
    MedicalWritingWorkingCopySaveRequest,
)

from .ai_gateway import AiTaskType
from .medical_writing_durable_jobs import (
    DurableJobExecutor,
    DurableJobResult,
    DurableJobStore,
)
from .medical_writing_content_quality import (
    DRAFTING_PROCESS_VOCABULARY_RE,
    INTERNAL_TRANSPORT_VOCABULARY_RE,
    iter_unresolved_draft_markers,
)
from .medical_writing_corpus_policy import CORPUS_GENERALIZATION_PROMPT_RULES
from .medical_writing_repository import RuntimeStoreError, StaleRuntimeStateError
from .medical_writing_authoring_prefill import SUPPORTED_ADOPT_PATHS
from .medical_writing_protocol_template import company_template_semantic_node_map


FULL_DRAFT_JOB_TYPE = "protocol_full_draft"
FULL_DRAFT_PROMPT_VERSION = "protocol_full_draft_v0_11"
FULL_DRAFT_ARTIFACT_SCHEMA = "protocol_full_draft_artifact_v10"
FULL_DRAFT_CHUNK_ARTIFACT_SCHEMA = "protocol_full_draft_chunk_v10"
FULL_DRAFT_DESCRIPTOR_VERSION = "protocol_full_draft_descriptor_v12"
LEGACY_FULL_DRAFT_ARTIFACT_SCHEMAS = {
    "protocol_full_draft_artifact_v3",
    "protocol_full_draft_artifact_v4",
    "protocol_full_draft_artifact_v5",
    "protocol_full_draft_artifact_v6",
    "protocol_full_draft_artifact_v7",
    "protocol_full_draft_artifact_v8",
    "protocol_full_draft_artifact_v9",
}
FULL_DRAFT_REVIEW_POLICY_VERSION = "protocol_full_draft_review_v0_3"
FULL_DRAFT_MINIMUM_BODY_CHARS = 80
# Four sections keep max-reasoning responses within the provider's bounded
# final-output budget.  An eight-section v0.4 batch was observed to end before
# its outer JSON object closed, leaving only a nested evidence object parsable.
FULL_DRAFT_CHUNK_SIZE = 4
# SMOKE-r2-3 ⑤（R27 收敛修订）：单批校验失败（模型回显畸变如 task_id 少
# 一位、正文残留草稿标记等模型输出格式问题）允许整批重新请求，最多
# FULL_DRAFT_CHUNK_ATTEMPTS 次尝试。证据：mwjob_d8ab5c5ab56d5f3238f6f413
# 第8批失败（task_id 回显 20261001→20260100 + 残留草稿标记），前7批全部
# 合格——格式性抖动弃掉整 jobs 数小时产出不成比例。身份边界不变：每次
# 重试都是全新 AiTaskRun（新run_id、全新校验），identity 门照常执行；
# 确定性失败（路由身份变化/上下文漂移/未配置）不重试，保持 fail-fast。
FULL_DRAFT_CHUNK_ATTEMPTS = 3
FULL_DRAFT_MAX_OUTPUT_TOKENS = 65_536
# R8 片Z（P1-45）：批级心跳上限——现场单批2~9.5分钟、末批20分钟无心跳。
FULL_DRAFT_HEARTBEAT_INTERVAL_SECONDS = 45.0


# ── P0-A（新纪元第2轮修订）：全文初稿装配完整性确定性门 ───────────────────
# 现场（NEW-13）：r10-A 导出件 9.2/9.3/9.4 三节正文逐字节相同——生成层只比
# section_id 序列，模型违反指令时全链无拦截。本门在生成/采纳/导出三层做
# 归一化跨节重复检测（>80 字相同正文出现于 ≥2 节即拒收/计缺口）。
FULL_DRAFT_DUPLICATE_BODY_MIN_CHARS = 80


class FullDraftDuplicateSectionsError(RuntimeStoreError):
    """P0-A 重复门的结构化拒绝（复测N1）：携带重复对供采纳面板逐节处置。

    duplicate_pairs: [{"sections": [{"section_id","section_number","heading"}...],
                      "shared_fragment_chars": N}]
    正文文案用节号+标题（人话），内部 section_id 仅在结构化字段中供处置
    回传，不进用户可见文本。
    """

    def __init__(self, message: str, duplicate_pairs: list[dict] | None = None,
                 undecided_section_ids: list[str] | None = None) -> None:
        super().__init__(message)
        self.duplicate_pairs = duplicate_pairs or []
        self.undecided_section_ids = undecided_section_ids or []


def normalize_full_draft_body(text: str) -> str:
    """装配重复检测的正文归一化：去除全部空白（含全角空白）。"""
    return re.sub(r"[\s\u3000]+", "", str(text or ""))


def find_full_draft_duplicate_sections(
    sections: Iterable[Mapping[str, Any]],
    *,
    text_key: str = "proposal_text",
) -> dict[str, list[str]]:
    """跨节正文重复检测（共享长片段口径）：返回 {共享片段: [节号...]}（≥2 节）。

    比对单位不是整节归一化文本（各节可有不同收尾），而是归一化后的
    80 字滑窗：任一节的某个 80 字窗口原样出现于另一节即记共享片段
    （现场 NEW-13 形态=同一段方法学正文被复制进多节、各节收尾不同）。
    短于窗口的通用短语不参与（不误伤）；窗口签名取共享区域首个窗口，
    值列表保持节序去重。
    """
    window = FULL_DRAFT_DUPLICATE_BODY_MIN_CHARS
    window_owners: dict[str, list[str]] = {}
    section_order: list[str] = []
    for item in sections or []:
        if not isinstance(item, Mapping):
            continue
        section_id = _text(item.get("section_id"))
        if not section_id:
            continue
        section_order.append(section_id)
        normalized = normalize_full_draft_body(item.get(text_key))
        fingerprints: set[str] = set()
        for start in range(0, max(0, len(normalized) - window + 1)):
            fingerprints.add(normalized[start:start + window])
        for fingerprint in fingerprints:
            owners = window_owners.setdefault(fingerprint, [])
            if section_id not in owners:
                owners.append(section_id)
    merged: dict[str, list[str]] = {}
    # 合并相邻窗口：同属一对（或多对）同节组合的连续窗口折叠为一条共享
    # 片段记录，签名取该组最小（字典序）窗口，保证一处装配重复只产一条。
    grouped: dict[tuple[str, ...], set[str]] = {}
    for fingerprint, owners in window_owners.items():
        if len(owners) < 2:
            continue
        key = tuple(owners)
        grouped.setdefault(key, set()).add(fingerprint)
    for owners, fingerprints in grouped.items():
        windows = sorted(fingerprints)
        signature = windows[0]
        merged[signature] = list(owners)
    return merged


def _duplicate_pairs_payload(
    duplicates: Mapping[str, list[str]],
    candidates: Mapping[str, Mapping[str, Any]],
) -> list[dict]:
    """重复对结构化载荷：节号+标题+共享片段长度（供采纳面板逐节三选一）。"""
    pairs: list[dict] = []
    for signature, section_ids in duplicates.items():
        pairs.append(
            {
                "sections": [
                    {
                        "section_id": section_id,
                        "section_number": str(
                            candidates.get(section_id, {}).get("section_number")
                            or ""
                        ),
                        "heading": str(
                            candidates.get(section_id, {}).get("heading") or ""
                        ),
                    }
                    for section_id in section_ids
                ],
                "shared_fragment_chars": len(signature),
            }
        )
    return pairs


def _duplicate_section_names(duplicates: Mapping[str, list[str]]) -> str:
    """去重保序的节号点名串（供拒收/缺口消息使用）。"""
    names: list[str] = []
    for section_ids in duplicates.values():
        for section_id in section_ids:
            if section_id not in names:
                names.append(section_id)
    return "、".join(names)


def classify_full_draft_chunk_failure(exc: Exception) -> str:
    """R6 片B′（P0-25）：批次失败分型，决定重试/跳过/快速失败。

    - ``capacity``：提供方容量/传输类（HTTP 507/5xx、空回包、重试梯预算
      耗尽）。与校验类共享同一有界重试预算；耗尽后跳过该批并标记，
      不再弃掉整单已生成批次（现场 r6-D：第8批507→整单失败→0可用输出）。
    - ``validation``：模型输出格式抖动（“未通过校验”）。原重试语义保留。
    - ``deterministic``：路由身份/上下文漂移等确定性失败，保持 fail-fast。
    """
    message = str(exc)
    diagnostics = getattr(exc, "diagnostics", None)
    if isinstance(diagnostics, dict):
        failure_code = str(diagnostics.get("failure_code") or "")
        http_status = diagnostics.get("http_status")
        if failure_code in {
            "provider_http_error",
            "provider_response_empty",
            "provider_transport_error",
            "provider_ladder_budget_exhausted",
        }:
            return "capacity"
        if isinstance(http_status, int) and http_status in {429, 500, 502, 503, 504, 507}:
            return "capacity"
    if "未通过校验" in message:
        return "validation"
    if "HTTP 507" in message or "HTTP 502" in message or "HTTP 503" in message or "HTTP 504" in message:
        return "capacity"
    return "deterministic"
# design.* paths whose authoritative mapping needs structured (dict) input; a
# prose decision answer would be silently dropped there, so such decisions
# fail closed instead of persisting nothing.
_DECISION_STRUCTURED_DESIGN_PATHS = frozenset(
    {"design.src_dmc", "design.phase1_parts", "design.arms_or_cohorts"}
)
FULL_DRAFT_DECISION_FACT_PATHS = tuple(
    sorted(
        {
            "picos.exploratory_endpoints",
            "picos.exploratory_objectives",
        }
        & SUPPORTED_ADOPT_PATHS
        - _DECISION_STRUCTURED_DESIGN_PATHS
    )
)

# A full-draft card may fill one whole, currently unconfirmed study-definition
# field.  It may not use a broad confirmed field as a convenient bucket for an
# unrelated operational choice.  Each field also has one owning section so a
# single user click cannot be duplicated across the document.
_DECISION_PATH_HEADING_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "picos.allowed_concomitant_rules": (
        re.compile(r"^允许的合并用药/治疗$"),
        re.compile(r"^合并用药/治疗$"),
    ),
    "picos.prohibited_concomitant_rules": (
        re.compile(r"^禁止的合并用药/治疗$"),
        re.compile(r"^合并用药/治疗$"),
    ),
    "picos.required_background_rules": (
        re.compile(r"^合并用药/治疗$"),
        re.compile(r"背景治疗"),
    ),
    "picos.assessment_timing_restrictions": (
        re.compile(r"^安全性评估$"),
        re.compile(r"^研究流程和评估$"),
    ),
    "picos.exploratory_objectives": (
        re.compile(r"探索性目的"),
        re.compile(r"^研究目的和终点$"),
    ),
    "picos.exploratory_endpoints": (
        re.compile(r"探索性终点"),
        re.compile(r"^研究目的和终点$"),
    ),
}

_SAMPLE_SIZE_NUMBER_RE = r"(\d+(?:\.\d+)?)"


def _z_value(alpha: float, one_sided: bool) -> float:
    """正态近似的双侧/单侧分位数（无 scipy 依赖，标准正态解析近似）。"""
    from statistics import NormalDist

    tail = alpha if one_sided else alpha / 2
    return NormalDist().inv_cdf(1 - tail)


# R9（第8轮末修订动作2）P0-18 输入层门：与 sample_size_consistency_check
# 同一正则族的广义声明解析——声明的例数形态（两组各N例/每组N例/N例/组/
# 需N例/组）、差值单位（分/%/次/米等连续量）、把握度前后置（80%把握度/
# 把握度80%）。比例型设计（外部锚点应答率，无连续SD/δ）解析不出差值→
# 判「样本量要素未齐」不拦截，避免误拦基准轮正向工艺（51/102/192）。
_SS_DECLARED_RES = (
    re.compile(r"(?:两组各|各组|每臂各?|每组)(?:需|约|需约|需要)?\s*" + _SAMPLE_SIZE_NUMBER_RE + r"\s*例"),
    re.compile(r"\b" + _SAMPLE_SIZE_NUMBER_RE + r"\s*例\s*/\s*组"),
    re.compile(r"需\s*" + _SAMPLE_SIZE_NUMBER_RE + r"\s*例\s*/?\s*组"),
)
_SS_DELTA_RES = (
    re.compile(
        r"(?:组间差(?:异)?|差值|差异|δ)\s*(?:为|是|=|约)?\s*"
        + _SAMPLE_SIZE_NUMBER_RE
        + r"\s*(?:分|%|次|米|mL|ml|kg|mmHg|点|个?单位)?"
    ),
    re.compile(r"δ\s*=\s*" + _SAMPLE_SIZE_NUMBER_RE),
)
_SS_POWER_RES = (
    re.compile(r"把握度\s*(?:达|为|≥|>=)?\s*(\d+(?:\.\d+)?)\s*%"),
    re.compile(r"(\d+(?:\.\d+)?)\s*%\s*把握度"),
)
_SS_ALPHA_RES = (
    re.compile(r"α\s*=\s*(0?\.\d+)"),
    re.compile(r"显著性水平\s*(?:为|是|=)?\s*(0\.\d+)"),
)


def sample_size_declaration_check(text: str) -> dict | None:
    """P0-18 输入层门校验器：声明例数 vs 假设复算（连续量公式）。

    返回：
    - None：文本不含样本量声明（不适用）；
    - {"status": "自洽", declared, required, detail}：解析齐且偏差≤±20%；
    - {"status": "不一致", declared, required, detail}：解析齐但复算与声明
      偏差>±20%——完成第二步（PICOS提交）必须阻断；
    - {"status": "样本量要素未齐", declared, required=None, detail}：声明了
      例数但假设不全（或比例型设计）——不阻断，生成层走悬置块。
    """
    raw = str(text or "")
    declared = None
    for pattern in _SS_DECLARED_RES:
        match = pattern.search(raw)
        if match:
            declared = float(match.group(1))
            break
    if declared is None:
        return None

    alpha = None
    for pattern in _SS_ALPHA_RES:
        match = pattern.search(raw)
        if match:
            alpha = float(match.group(1))
            break
    power = None
    for pattern in _SS_POWER_RES:
        match = pattern.search(raw)
        if match:
            power = float(match.group(1)) / 100
            break
    sd = None
    sd_match = re.search(
        r"(?:标准差|SD)\s*(?:为|是|=|约)?\s*" + _SAMPLE_SIZE_NUMBER_RE, raw
    )
    if sd_match:
        sd = float(sd_match.group(1))
    delta = None
    for pattern in _SS_DELTA_RES:
        match = pattern.search(raw)
        if match:
            delta = float(match.group(1) or match.group(2) or 0)
            break
    one_sided = bool(re.search(r"单侧", raw))

    missing = [
        label
        for label, value in (
            ("α", alpha), ("把握度", power), ("SD", sd), ("组间差/δ", delta),
        )
        if value is None
    ]
    if (
        missing
        or not alpha
        or not power
        or not sd
        or not delta
        or sd <= 0
        or delta <= 0
    ):
        return {
            "status": "样本量要素未齐",
            "declared_per_group": int(declared),
            "required_per_group": None,
            "detail": "样本量假设要素不全（缺失：" + "、".join(missing) + "）；无法复算，不得声称样本量已确认。",
        }
    z_alpha = _z_value(alpha, one_sided)
    z_beta = _z_value(1 - power, True)
    required = 2 * ((z_alpha + z_beta) ** 2) * (sd ** 2) / (delta ** 2)
    required_ceil = max(2, int(required + 0.999))
    ratio = declared / required_ceil
    side = "单侧" if one_sided else "双侧"
    if ratio < 0.8 or ratio > 1.25:
        return {
            "status": "不一致",
            "declared_per_group": int(declared),
            "required_per_group": required_ceil,
            "detail": (
                f"按您输入的差值/SD/α/把握度（组间差{delta:g}、SD{sd:g}、"
                f"α={alpha:g}{side}、把握度{int(power * 100)}%）复算需"
                f"{required_ceil}例/组，当前声明{int(declared)}例/组：请修正声明或调整假设。"
            ),
        }
    return {
        "status": "自洽",
        "declared_per_group": int(declared),
        "required_per_group": required_ceil,
        "detail": f"按声明参数复算约需 {required_ceil} 例/组，与声明一致。",
    }


# P1-53（新纪元第1轮修订·E9，规格 SPEC_sample_size_revision_gate_P1-53.md）
# 样本量修订路径三件套：口径指纹、强制重算、单双侧混写禁令。
# 现场根因：P0-18 输入层门只校验『完成第二步』时点的参数组合，假设事后
# 修订（AD：28%vs18% → 38%vs18%）后陈旧基数（850/567/283）不重算就一路
# 走到导出件——比例型文本声明总数无『每组』字样，P0-18 的声明正则族
# 根本不适用。
_SS_PROPORTION_PAIR_RES = (
    re.compile(
        r"(?:应答率|有效率|反应率|缓解率|发生率)\s*(\d+(?:\.\d+)?)\s*%"
        r"\s*(?:与|和|vs\.?|对比|对)\s*(?:对照)?\s*"
        r"(?:应答率|有效率|反应率|缓解率|发生率)?\s*(\d+(?:\.\d+)?)\s*%"
    ),
    re.compile(
        r"(\d+(?:\.\d+)?)\s*%\s*(?:与|和|vs\.?|对比|对)\s*"
        r"(?:对照(?:应答率|有效率|反应率|缓解率|发生率)?\s*)?"
        r"(\d+(?:\.\d+)?)\s*%"
    ),
)
_SS_TOTAL_WITH_ALLOCATION_RE = re.compile(
    r"共?[约]?\s*(\d[\d,，\s]*)\s*例\s*[（(]\s*(\d[\d,，\s]*)\s*[/／]\s*(\d[\d,，\s]*)\s*[)）]"
)
_SS_BARE_TOTAL_RE = re.compile(r"共[约]?\s*(\d[\d,，\s]*)\s*例")


def _parse_sample_size_assumptions(raw: str) -> dict:
    """P1-53 假设五要素解析（单双侧|α|把握度|δ|SD，比例型由 p 对推导）。

    与 sample_size_declaration_check 同一正则族取 α/把握度/SD/δ；比例型
    设计（无连续 SD/δ）额外解析 p1/p2（百分点），δ=|p1-p2|、
    SD=√(p̄(1-p̄))。任一要素缺失时对应值为 None（不编造）。
    """
    alpha = None
    for pattern in _SS_ALPHA_RES:
        match = pattern.search(raw)
        if match:
            alpha = float(match.group(1))
            break
    power = None
    for pattern in _SS_POWER_RES:
        match = pattern.search(raw)
        if match:
            power = float(match.group(1)) / 100
            break
    sd = None
    sd_match = re.search(
        r"(?:标准差|SD)\s*(?:为|是|=|约)?\s*" + _SAMPLE_SIZE_NUMBER_RE, raw
    )
    if sd_match:
        sd = float(sd_match.group(1))
    delta = None
    for pattern in _SS_DELTA_RES:
        match = pattern.search(raw)
        if match:
            delta = float(match.group(1) or match.group(2) or 0)
            break
    p1 = p2 = None
    for pattern in _SS_PROPORTION_PAIR_RES:
        match = pattern.search(raw)
        if match:
            first, second = float(match.group(1)), float(match.group(2))
            if 0 < first < 100 and 0 < second < 100 and first != second:
                p1, p2 = first / 100, second / 100
            break
    if delta is None and p1 is not None:
        delta = abs(p1 - p2)
    if sd is None and p1 is not None:
        pooled = (p1 + p2) / 2
        sd = (pooled * (1 - pooled)) ** 0.5
    return {
        "one_sided": bool(re.search(r"单侧", raw)),
        "alpha": alpha,
        "power": power,
        "sd": sd,
        "delta": delta,
        "p1": p1,
        "p2": p2,
    }


def sample_size_fingerprint(text: str) -> str | None:
    """P1-53 口径指纹：五要素齐才产 sha256(单双侧|α|把握度|δ|SD)[:16]。

    要素不全（含纯文本无样本量内容）返回 None——首存不产指纹、不触发
    修订比对；比例型设计的 δ/SD 由 p 对推导后同样入指纹（AD 现场：
    28%→38% 假设修订必须改变指纹）。
    """
    assumptions = _parse_sample_size_assumptions(str(text or ""))
    alpha = assumptions["alpha"]
    power = assumptions["power"]
    sd = assumptions["sd"]
    delta = assumptions["delta"]
    if not alpha or not power or sd is None or delta is None or sd <= 0 or delta <= 0:
        return None
    canonical = "{}|{:.6g}|{:.6g}|{:.6g}|{:.6g}".format(
        "单侧" if assumptions["one_sided"] else "双侧",
        alpha,
        power,
        delta,
        sd,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def sample_size_revision_check(text: str) -> dict | None:
    """P1-53 强制重算门：假设修订（指纹变化）后的基数复算。

    比基础 declaration_check 多两类声明/推导形态（只在修订路径启用，
    首存比例型仍按 P0-18 语义不拦）：
    - 声明形态：总数+分配括号『共850例（567/283）』——取较小臂为对照
      口径（1:1 每组需量的近似，±20% 容差吸收 2:1 的 1.125 放大）；
      裸『共N例』按 1:1 折半；
    - 推导形态：比例型 p1/p2——n=(z_α+z_β)²[p₁(1-p₁)+p₂(1-p₂)]/δ²
      （与成型方案口径一致的数量级校验）。
    """
    raw = str(text or "")
    assumptions = _parse_sample_size_assumptions(raw)
    alpha = assumptions["alpha"]
    power = assumptions["power"]
    sd = assumptions["sd"]
    delta = assumptions["delta"]
    declared = None
    for pattern in _SS_DECLARED_RES:
        match = pattern.search(raw)
        if match:
            declared = float(match.group(1))
            break
    if declared is None:
        allocation_match = _SS_TOTAL_WITH_ALLOCATION_RE.search(raw)
        if allocation_match:
            arms = [
                float(re.sub(r"[,，\s]", "", allocation_match.group(index)))
                for index in (2, 3)
            ]
            if arms[0] > 0 and arms[1] > 0:
                declared = min(arms)
        else:
            bare_match = _SS_BARE_TOTAL_RE.search(raw)
            if bare_match:
                declared = float(re.sub(r"[,，\s]", "", bare_match.group(1))) / 2
    if declared is None:
        return None
    missing = [
        label
        for label, value in (
            ("α", alpha), ("把握度", power), ("δ", delta), ("SD", sd),
        )
        if value is None
    ]
    if missing or not alpha or not power or delta is None or sd is None or delta <= 0 or sd <= 0:
        return {
            "status": "样本量要素未齐",
            "declared_per_group": int(declared),
            "required_per_group": None,
            "detail": "样本量假设要素不全（缺失：" + "、".join(missing) + "）；无法按修订后假设复算。",
        }
    z_alpha = _z_value(alpha, assumptions["one_sided"])
    z_beta = _z_value(1 - power, True)
    if assumptions["p1"] is not None and assumptions["p2"] is not None:
        p1, p2 = assumptions["p1"], assumptions["p2"]
        required = ((z_alpha + z_beta) ** 2) * (
            p1 * (1 - p1) + p2 * (1 - p2)
        ) / (delta ** 2)
    else:
        required = 2 * ((z_alpha + z_beta) ** 2) * (sd ** 2) / (delta ** 2)
    required_ceil = max(2, int(required + 0.999))
    ratio = declared / required_ceil
    side = "单侧" if assumptions["one_sided"] else "双侧"
    if ratio < 0.8 or ratio > 1.25:
        return {
            "status": "不一致",
            "declared_per_group": int(declared),
            "required_per_group": required_ceil,
            "detail": (
                f"假设修订后（{side}α={alpha:g}、把握度{int(power * 100)}%、"
                f"δ={delta:g}{'（比例推导）' if assumptions['p1'] is not None else ''}）"
                f"复算约需{required_ceil}例/组（对照口径），当前声明基数对应"
                f"{int(declared)}例/组：请按修订后假设重算并更新声明基数。"
            ),
        }
    return {
        "status": "自洽",
        "declared_per_group": int(declared),
        "required_per_group": required_ceil,
        "detail": f"按修订后假设复算约需 {required_ceil} 例/组，与声明基数一致。",
    }


def sample_size_sidedness_mixing_check(text: str) -> bool:
    """P1-53 单双侧混写禁令：同一统计章内单双侧不得混指同一 α/把握度组合。

    『双单侧』（TOST 等效性检验）与『双侧可信/置信区间』（估计语境）
    是合法表述，不计混写；仅在章节含样本量声明语境时判定。
    """
    raw = str(text or "")
    if "单侧" not in raw or "双侧" not in raw:
        return False
    one_sided = re.search(r"(?<!双)单侧", raw)
    two_sided = re.search(r"双侧(?!(?:可信|置信|CI|ci))", raw)
    if not (one_sided and two_sided):
        return False
    has_sample_size_context = "样本量" in raw or sample_size_declaration_check(raw) is not None
    return bool(has_sample_size_context)


def _rewrite_declared_sample_size(text: str, declared: int, required: int) -> str:
    """生成层护栏②：不一致节的声明数字改写为复算值（含成对总数）。"""
    replaced = text
    pairs = (
        (f"两组各{declared}例", f"两组各{required}例"),
        (f"每组{declared}例", f"每组{required}例"),
        (f"{declared}例/组", f"{required}例/组"),
        (f"需{declared}例/组", f"需{required}例/组"),
        (f"共{2 * declared}例", f"共{2 * required}例"),
    )
    for old, new in pairs:
        replaced = replaced.replace(old, new)
    return replaced


def apply_sample_size_guard_to_section(section_item: dict, anchor: str = "") -> None:
    """R9 P0-18 生成层护栏：统计章声明数字不得照抄。

    - 复算不一致：声明数字改写为复算值（成对总数同步），并追加复算
      注记（审计透明）；sample_size_check 记「不一致」。
    - 要素未齐（含比例型设计）：正文前插入 P1-21 式悬置块（含锁定
      条件），数字保留但标记待确认。
    - 自洽：不动。
    第9轮末修订（P1-48）溯源收官：凡含样本量声明的统计章——有锚点附
    『（样本量依据：{anchor}）』上纸；无锚点如实标注『假设未具名溯源，
    建议引用外部先例』。
    就地修改 section_item（proposal_text 与 sample_size_check）。
    """
    section_number = str(section_item.get("section_number") or "")
    heading = str(section_item.get("heading") or "")
    if not (section_number.startswith("9") or "统计" in heading or "样本量" in heading):
        return
    text = str(section_item.get("proposal_text") or "")
    # P1-53（新纪元第1轮修订·E9）单双侧混写禁令：先于声明形态判定——
    # 混写文本可能解析不出声明例数；同一 α/把握度组合只能有一个口径
    # （两套 z 值差可达22%例数），混写即插悬置块（导出层据此计缺口→
    # 草案-N）。『双单侧』（TOST）与『双侧可信/置信区间』不算混写。
    if sample_size_sidedness_mixing_check(text):
        section_item["sample_size_check"] = {
            "status": "口径混写",
            "detail": "同一统计章内『单侧』与『双侧』混指同一α/把握度组合。",
        }
        section_item["proposal_text"] = (
            "【样本量口径混写待确认：本节同时出现『单侧』与『双侧』的检验"
            "设定表述——同一α/把握度组合只能有一个口径（两套z值差可达22%"
            "例数）；锁定条件：统一口径并按统一口径重算样本量后解除，"
            "正式稿不得带此标记。】" + text
        )
        return
    check = sample_size_declaration_check(text)
    if check is None:
        return
    section_item["sample_size_check"] = check
    status = check.get("status")
    if status == "不一致":
        declared = int(check.get("declared_per_group") or 0)
        required = int(check.get("required_per_group") or 0)
        if declared and required:
            rewritten = _rewrite_declared_sample_size(text, declared, required)
            rewritten += (
                f"（样本量复算注记：按声明的组间差/SD/α/把握度复算需{required}例/组，"
                f"原文声明{declared}例/组与复算不一致，正文已按复算值改写；"
                "请核对假设或修正声明后重新生成。）"
            )
            section_item["proposal_text"] = rewritten
    elif status == "样本量要素未齐":
        declared = int(check.get("declared_per_group") or 0)
        section_item["proposal_text"] = (
            f"【样本量待确认：当前声明每组{declared}例，但样本量假设要素不全"
            "（缺组间差/SD/α/把握度），系统无法复算；锁定条件：补齐假设并使"
            "复算与声明一致（差值≤±20%）后解除，正式稿不得带此标记。】" + text
        )
    # P1-48：溯源标注（有锚点=具名依据上纸；无锚点=如实声明并建议补引）。
    # E10（新纪元第1轮修订）：溯源状态同时落结构化字段——审阅侧无需
    # 解析正文即可看到『假设待定/已具名』（成型方案具名先例是标配）。
    anchor_text = str(anchor or "").strip()
    if anchor_text:
        section_item["sample_size_provenance"] = f"已具名（{anchor_text}）"
        section_item["proposal_text"] += (
            f"（样本量依据：{format_provenance_reference(anchor_text)}）"
        )
    else:
        section_item["sample_size_provenance"] = "假设待定（未具名溯源，建议引用外部先例）"
        section_item["proposal_text"] += "（样本量假设未具名溯源，建议引用外部先例。）"


# ── E11（新纪元第1轮修订）：统计章分节装配五件套 ─────────────────────────
# 规格 SPEC_statistical_chapter_assembly_20261007.md（P1-49，R8 审阅者B
# DM/Stat 四件差距+防火墙）。对齐成型方案统计章结构（8.1-8.7）：
# 分析集成员规则（FAS/SS/PP 三段式）、多重性终点族（指向存在的终点）、
# 敏感性双法（MI + tipping/跳转至参考）、顺序检验声明、非盲统计师防火墙。
_STAT_ASSEMBLY_APPLICABILITY_RE = re.compile(r"统计|样本量|分析集|终点|多重性")
_STAT_ASSEMBLY_SET_RES = (
    ("FAS", re.compile(r"全分析集|(?<![A-Za-z])FAS(?![A-Za-z])")),
    ("SS", re.compile(r"安全性分析集|安全分析集|安全集|(?<![A-Za-z])SS(?![A-Za-z])")),
    (
        "PP",
        re.compile(
            r"符合方案集|符合方案分析集|(?<![A-Za-z])PPS?(?![A-Za-z])|Per[- ]?Protocol"
        ),
    ),
)
_STAT_MEMBER_RULE_RE = re.compile(
    r"重大方案偏离|方案偏离|入选标准|随机入组|至少一次[^\n。]{0,12}(?:治疗|给药|用药)"
    r"|所有随机[^\n。]{0,24}(?:纳入|进入|接受)"
    r"|接受研究[^\n。]{0,12}(?:给药|治疗)[^\n。]{0,20}(?:受试者|患者)"
    r"|(?:FAS|SS|PP|PPS)[^\n。]{0,16}(?:包括|指|定义为|成员)"
)
_STAT_SENSITIVITY_MI_RE = re.compile(
    r"多重填补|(?<![A-Za-z])MI(?![A-Za-z])|multiple imputation", re.IGNORECASE
)
_STAT_SENSITIVITY_SECONDARY_RE = re.compile(
    r"tipping|临界点|跳转至参考|jump to reference", re.IGNORECASE
)
_STAT_FIREWALL_RE = re.compile(r"防火墙|非盲统计师|揭盲[^\n。]{0,12}隔离")
_STAT_ORDERED_TEST_RE = re.compile(
    r"顺序检验|检验顺序|gatekeeping|逐级检验|层级检验|Holm递阶|递阶策略|递阶检验",
    re.IGNORECASE,
)
_STAT_ENDPOINT_FAMILY_TOKENS = (
    "主要终点",
    "关键次要终点",
    "次要终点",
    "探索性终点",
)


def statistics_assembly_check(
    text: str, *, endpoint_families: dict[str, bool] | None = None
) -> dict:
    """E11 五件套在场检查（统计章为统计章结构完整性口径）。

    返回 {"missing": [...], "invalid_multiplicity_targets": [...]}；
    非统计语境文本（无统计/样本量/分析集/终点/多重性关键词）不适用，
    missing 恒空（不误伤非统计章节）。endpoint_families 提供时（生成层
    从 PICOS 结构化终点清单注入），多重性声明引用的终点族必须存在
    （R1-B 反例：3.2 次要终点全空而声明控制对象）。
    """
    raw = str(text or "")
    if not _STAT_ASSEMBLY_APPLICABILITY_RE.search(raw):
        return {"missing": [], "invalid_multiplicity_targets": []}
    missing: list[str] = []
    set_hits = [
        name
        for name, pattern in _STAT_ASSEMBLY_SET_RES
        if pattern.search(raw)
    ]
    if len(set_hits) < len(_STAT_ASSEMBLY_SET_RES) or not _STAT_MEMBER_RULE_RE.search(raw):
        missing.append("分析集成员规则")
    mentioned_families = [
        token for token in _STAT_ENDPOINT_FAMILY_TOKENS if token in raw
    ]
    invalid_targets: list[str] = []
    # 多重性终点族与顺序检验声明是无条件声明位（规格：声明位必须在场，
    # 内容未声明时不编造——挂起块即如实占位）；多重性声明引用的结构化
    # 终点族必须存在（endpoint_families 提供时逐族校验）。
    if not mentioned_families:
        missing.append("多重性终点族")
    elif endpoint_families is not None:
        for family in mentioned_families:
            if family in endpoint_families and not endpoint_families[family]:
                invalid_targets.append(family)
        if invalid_targets:
            missing.append("多重性终点族")
    if not _STAT_ORDERED_TEST_RE.search(raw):
        missing.append("顺序检验声明")
    if not (_STAT_SENSITIVITY_MI_RE.search(raw) and _STAT_SENSITIVITY_SECONDARY_RE.search(raw)):
        missing.append("敏感性双法")
    if not _STAT_FIREWALL_RE.search(raw):
        missing.append("非盲统计师防火墙")
    return {"missing": missing, "invalid_multiplicity_targets": invalid_targets}


def apply_statistics_assembly_guard_to_section(
    section_item: dict, *, endpoint_families: dict[str, bool] | None = None
) -> None:
    """E11 生成层：统计章五件套缺件挂起块（未声明不编造，导出层计缺口）。

    - 缺件（含多重性引用不存在终点族）：正文前插入挂起块，逐件点名并
      给锁定条件；statistics_assembly_check 记录落工件；
    - 五件齐：不动。
    """
    section_number = str(section_item.get("section_number") or "")
    heading = str(section_item.get("heading") or "")
    if not (section_number.startswith("9") or "统计" in heading or "样本量" in heading):
        return
    text = str(section_item.get("proposal_text") or "")
    if not text.strip():
        return
    check = statistics_assembly_check(text, endpoint_families=endpoint_families)
    section_item["statistics_assembly_check"] = check
    missing = check.get("missing") or []
    if not missing:
        return
    invalid_targets = check.get("invalid_multiplicity_targets") or []
    named = "、".join(missing)
    detail = ""
    if invalid_targets:
        detail = (
            "多重性声明引用了结构化终点清单中不存在的终点族（"
            + "、".join(invalid_targets)
            + "）；"
        )
    section_item["proposal_text"] = (
        f"【统计章分节装配待确认：{detail}本统计章缺少：{named}"
        "（对齐成型方案统计章结构：分析集成员规则/多重性终点族/敏感性双法"
        "/顺序检验声明/非盲统计师防火墙）；锁定条件：按已确认设计事实逐件"
        "补齐后解除，未声明处不得编造（如检验树），正式稿不得带此标记。】"
        + text
    )


_INTERNAL_ANCHOR_RE = re.compile(r"§|内部\s*IB", re.IGNORECASE)
_INTERNAL_IB_VERSION_RE = re.compile(r"IB\s*(v?\d+(?:\.\d+)*)")


def format_provenance_reference(source_text: str, *, study_code: str = "") -> str:
    """溯源串引用格式化层（第4轮·第五刀，NEW-29 根因修）。

    内部锚点串（含'§'或'内部IB'）转为可回验引用：
    '数据来源：申办方内部资料（IB v3.1，<研究代号>）'——IB 版本号从原文
    提取，研究代号由调用方注入（未提供时省略）；上纸文本不含裸'§'。
    已是规范引用（无内部锚点记号）的原样通过。完整原始锚点由调用方保留
    在结构化字段（dose_source 等审阅面元数据），定位信息不丢失。
    """
    raw = str(source_text or "").strip()
    if not raw or not _INTERNAL_ANCHOR_RE.search(raw):
        return raw
    version_match = _INTERNAL_IB_VERSION_RE.search(raw)
    version = f" {version_match.group(1)}" if version_match else ""
    study = f"，{study_code}" if str(study_code or "").strip() else ""
    return f"数据来源：申办方内部资料（IB{version}{study}）"


_DOSING_SECTION_RE = re.compile(r"^(?:6\.2)(?:\.\d+)?$|给药|研究治疗|研究用药")
# P0-27（第10轮末修订）：剂量单位存在性——BE204 现场全文 mg/毫克 0 命中
# 而一句话正文过门。单位族按基准轮口径：mg/毫克/µg/μg/微克/IU/国际单位。
_DOSE_UNIT_RE = re.compile(r"mg|毫克|µg|μg|微克|IU|国际单位", re.IGNORECASE)


def apply_full_draft_content_guards(
    sections: Iterable[Mapping[str, Any]],
    *,
    anchor: str = "",
    endpoint_families: dict[str, bool] | None = None,
) -> None:
    """全文初稿内容守卫统一入口（第3轮·守卫完整性）。

    样本量门/剂量门/统计章分节装配门必须对到达工作副本的每一份正文候选
    生效——第2轮复测实证守卫只接在 chunk 完成路径（run_job 持久化前）
    时，任何旁路采纳（逐节候选/快采/手工带出）都会把无守卫标记的正文
    送上纸面（NC401 现场：工件有锚点注记、导出无）。所有采纳路径统一
    调本函数；导出层另有'守卫标记缺失'三方一致性断言兜底。
    """
    for item in sections:
        apply_sample_size_guard_to_section(item, anchor=anchor)
        apply_dose_presence_guard_to_section(item)
        apply_statistics_assembly_guard_to_section(
            item, endpoint_families=endpoint_families
        )


def apply_dose_presence_guard_to_section(
    section_item: dict, source: str = ""
) -> None:
    """P0-27 生成层：给药/研究治疗章的剂量存在性检查。

    owner 裁定边界内行为（研究药物自身数据不可外查）：剂量单位 0 命中
    时不编造剂量——显性标记『剂量缺失』并提示『需IB/立项补剂量方案』，
    正文不阻断生成但带悬置提示随工件持久化（导出层据此计缺口→草案-N）。

    E13（新纪元第1轮修订）：剂量已载明时补『剂量出处』——有具名出处
    （IB 版本/立项剂量方案）即引用上纸；未具名时如实标注待标注（与
    样本量假设溯源同族，不拦生成）。
    """
    section_number = str(section_item.get("section_number") or "")
    heading = str(section_item.get("heading") or "")
    if not (_DOSING_SECTION_RE.search(section_number) or _DOSING_SECTION_RE.search(heading)):
        return
    text = str(section_item.get("proposal_text") or "")
    if not text.strip():
        return
    if not _DOSE_UNIT_RE.search(text):
        section_item["dose_check"] = {
            "status": "剂量缺失",
            "detail": "给药章节未出现任何剂量单位（mg/毫克/µg/μg/微克/IU/国际单位）。",
        }
        section_item["proposal_text"] = (
            "【剂量待确认：本节未载明研究药物的剂量与规格（无 mg/毫克/IU 等"
            "剂量单位）；需IB/立项补剂量方案后写入，正式稿不得带此标记。】" + text
        )
        return
    source_text = str(source or "").strip()
    if source_text:
        section_item["dose_source"] = source_text
        # 第五刀：上纸引用过格式化层（内部锚点→可回验引用；完整原始锚点
        # 保留在 dose_source 审阅面元数据）。
        section_item["proposal_text"] += (
            f"（剂量出处：{format_provenance_reference(source_text)}）"
        )
    else:
        section_item["dose_source"] = ""
        section_item["proposal_text"] += (
            "（剂量出处待标注：请引用IB版本或立项剂量方案作为剂量依据。）"
        )


def sample_size_consistency_check(text: str) -> dict | None:
    """NEW-14/44 内容族③（R27 第3轮修订）：统计章样本量算术自洽校验。

    从生成文本中提取声明参数（每组例数、α、把握度、SD、δ）并按
    n ≥ 2·(z_α+z_β)²·SD²/δ² 复算；声明与复算不一致或参数缺失即判
    「样本量要素未齐」。文本不含样本量声明时返回 None。
    """
    raw = str(text or "")
    if not ("样本量" in raw or "每组" in raw):
        return None
    declared_match = re.search(
        r"每组(?:需|约|需约|需要)?\s*" + _SAMPLE_SIZE_NUMBER_RE + r"\s*例", raw
    ) or re.search(
        r"\b" + _SAMPLE_SIZE_NUMBER_RE + r"\s*例\s*/\s*组", raw
    )
    if declared_match is None:
        return None
    declared = float(declared_match.group(1))

    missing: list[str] = []
    alpha_match = re.search(r"α\s*=\s*(0?\.\d+)|α\s*=\s*(0?\.\d+)", raw)
    alpha = float(alpha_match.group(1) or alpha_match.group(2) or 0) if alpha_match else None
    if alpha is None:
        missing.append("α")
    power_match = re.search(r"把握度\s*(?:达|为|≥|>=)?\s*(\d+(?:\.\d+)?)\s*%", raw)
    power = float(power_match.group(1)) / 100 if power_match else None
    if power is None:
        missing.append("把握度")
    sd_match = re.search(
        r"(?:标准差|SD)\s*(?:为|是|=|约)?\s*" + _SAMPLE_SIZE_NUMBER_RE, raw
    )
    sd = float(sd_match.group(1)) if sd_match else None
    if sd is None:
        missing.append("SD")
        missing.append("标准差") if False else None
    delta_match = re.search(
        r"(?:差异|δ|组间差异)[^。；]*?" + _SAMPLE_SIZE_NUMBER_RE + r"\s*次?\s*/\s*(?:24小时|日|天)|δ\s*=\s*" + _SAMPLE_SIZE_NUMBER_RE,
        raw,
    )
    delta = float(delta_match.group(1) or delta_match.group(2) or 0) if delta_match else None
    if delta is None:
        missing.append("δ")
    one_sided = bool(re.search(r"单侧", raw))

    if missing or not alpha or not power or not sd or not delta or sd <= 0 or delta <= 0:
        detail = "统计要素未齐（缺失：" + "、".join(sorted(set(missing))) + "）；"
        return {
            "status": "样本量要素未齐",
            "declared_per_group": int(declared),
            "required_per_group": None,
            "detail": detail + "不得声称样本量已确认。",
        }
    # z_α：单侧取全尾、双侧取半尾；z_β：恒取全尾 inv_cdf(1-β)。
    z_alpha = _z_value(alpha or 0.05, one_sided)
    z_beta = _z_value(1 - power, True)
    required = 2 * ((z_alpha + z_beta) ** 2) * (sd ** 2) / (delta ** 2)
    required_ceil = max(2, int(required + 0.999))
    ratio = declared / required_ceil if required_ceil else 0
    if ratio < 0.8 or ratio > 1.25:
        return {
            "status": "样本量要素未齐",
            "declared_per_group": int(declared),
            "required_per_group": required_ceil,
            "detail": (
                f"按声明参数（δ={delta}、SD={sd}、α={alpha}、"
                f"{'单侧' if one_sided else '双侧'}、把握度{int(power * 100)}%）复算约需 "
                f"{required_ceil} 例/组，与声明的 {int(declared)} 例/组不一致"
                "（偏差超过±20%）；样本量要素未齐，不得声称已确认。"
            ),
        }
    return {
        "status": "自洽",
        "declared_per_group": int(declared),
        "required_per_group": required_ceil,
        "detail": f"按声明参数复算约需 {required_ceil} 例/组，与声明一致。",
    }


_PLACEHOLDER_RE = re.compile(
    r"(?:^|[\s，。；：])(?:待补充|待确认|待定|TBD|TODO|不适用|无适用内容|由方案规定|见方案规定)(?:$|[\s，。；：])",
    re.IGNORECASE,
)
_REQUIRED_REVIEW_HEADING_RE = re.compile(
    r"^(?:方案概要|研究目的和终点|主要目的和主要终点|主要终点.*|研究设计|总体设计|"
    r"确证性设计与假设依据|随机化|盲法与揭盲|研究人群|研究人群选择及依据|"
    r"入选标准|排除标准|统计分析|(?:主要)?估计目标.*|样本量.*|非劣效.*|"
    r"期中分析.*|多重性.*|剂量选择.*|对照选择.*|研究药物相关风险|"
    r"妊娠事件(?:的报告与随访)?|避孕的规定与方法|安全信息报告途径)$",
    re.IGNORECASE,
)
_REQUIRED_REVIEW_CONTENT_RE = re.compile(
    r"主要终点|估计目标|伴发事件|样本量|计划入组|非劣效界值|期中分析|alpha|α|"
    r"剂量选择|对照选择|核心人群",
    re.IGNORECASE,
)
_CORPUS_CONDUCT_RE = re.compile(
    r"避孕|妊娠.{0,24}(?:报告|随访|结局)|不良事件.{0,20}(?:是指|定义|记录|报告)|"
    r"严重不良事件.{0,30}(?:记录|报告)|剂量(?:调整|暂停|减量)|给药中断|永久停药|"
    r"合并用药|禁用药|限制用药|洗脱|救援治疗|IWRS|交互式网络应答|"
    r"侵入性操作|全分析集|符合方案集|安全性分析集",
    re.IGNORECASE,
)
_DESIGN_RESTATEMENT_SIGNALS = (
    re.compile(r"计划入组\s*\d+\s*例"),
    re.compile(r"\d+(?:\.\d+)?\s*mg", re.IGNORECASE),
    re.compile(r"主要终点"),
    re.compile(r"随机"),
    re.compile(r"双盲"),
)
_DESIGN_RESTATEMENT_ALLOWED_HEADING_RE = re.compile(
    r"方案概要|研究设计|研究目的和终点|主要目的和主要终点|样本量",
    re.IGNORECASE,
)
_SOURCE_QUALIFICATION_RE = re.compile(
    r"仅用于(?:功能|隔离)?验收|仅供示例|示例参数|合成参数|合成剂量|假设参数"
)
_CORPUS_SOURCE_TYPES = {
    "company_protocol_reference_corpus",
    "shared_protocol_reference_corpus",
    "shared_phase1_protocol_reference_corpus",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _body_blocks(blocks: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(block)
        for block in blocks
        if str(block.get("block_type") or "") == "paragraph"
        and str(block.get("block_id") or "").strip()
        and str(block.get("source_kind") or "") != "medical_writing_intervention_rules"
    ]


def _body_text(blocks: Iterable[Mapping[str, Any]]) -> str:
    return "\n".join(
        _text(block.get("text"))
        for block in _body_blocks(blocks)
        if _text(block.get("text"))
    ).strip()


def _is_substantive(text: str) -> bool:
    normalized = _text(text)
    return bool(normalized) and len(normalized) >= FULL_DRAFT_MINIMUM_BODY_CHARS and not _PLACEHOLDER_RE.search(normalized)


def _safe_project_path(project_id: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(project_id))
    return token[:120] or "project"


class MedicalWritingFullDraftService:
    """Composition-root service for durable full-draft jobs and adoption."""

    def __init__(
        self,
        service_resolver: Callable[[str], Any],
        artifact_root: Path,
    ) -> None:
        self.service_resolver = service_resolver
        self.artifact_root = Path(artifact_root).expanduser().resolve()

    def _service(self, project_id: str) -> Any:
        service = self.service_resolver(project_id)
        if service is None or not hasattr(service, "repo"):
            raise RuntimeStoreError("medical writing full-draft service is not configured")
        return service

    @staticmethod
    def _binding(repo: Any, project_id: str, document: Any) -> dict[str, Any]:
        resolver = getattr(repo, "authoritative_study_definition_binding", None)
        if callable(resolver):
            values = resolver(project_id)
            study_id, revision, digest = values
        else:
            study_id = str(getattr(document, "source_study_definition_id", "") or "")
            revision = getattr(document, "source_study_definition_revision", None)
            digest = str(getattr(document, "source_study_definition_sha256", "") or "")
        if any((study_id, revision is not None, digest)) and not all((study_id, revision is not None, digest)):
            raise RuntimeStoreError("当前研究设计绑定不完整，全文初稿已停止")
        return {
            "id": str(study_id or ""),
            "revision": int(revision) if revision is not None else None,
            "sha256": str(digest or ""),
        }

    def _working_copy_blocks(self, repo: Any, project_id: str, section: Any) -> tuple[int, list[dict[str, Any]]]:
        current = repo.working_copy(project_id, section.section_id)
        if current.revision >= 1:
            return int(current.revision), [dict(block) for block in current.content_blocks]
        return 0, [dict(block) for block in section.content_blocks]

    def candidate_is_current(self, project_id: str, job: Any) -> bool:
        """Return whether a completed candidate still targets the current draft.

        This is used only to rediscover a durable candidate after a browser
        refresh.  Once the document binding, version, section revision, or
        target body changes, the older candidate remains in history but is no
        longer offered as the current review item.
        """
        try:
            artifact = self.read_artifact(project_id, job)
            service = self._service(project_id)
            repo = service.repo
            document = repo.protocol(project_id)
            if str(document.document_id) != str(artifact.get("document_id") or ""):
                return False
            if str(document.version) != str(artifact.get("document_version") or ""):
                return False
            if self._binding(repo, project_id, document) != artifact.get("study_definition"):
                return False
            targets = artifact.get("target_sections") or []
            if not targets:
                return False
            for target in targets:
                section_id = _text(target.get("section_id"))
                body_block_id = _text(target.get("body_block_id"))
                if not section_id or not body_block_id:
                    return False
                current = repo.working_copy(project_id, section_id)
                if int(current.revision) != int(target.get("expected_revision") or 0):
                    return False
                body = next(
                    (
                        _text(block.get("text"))
                        for block in current.content_blocks
                        if _text(block.get("block_id")) == body_block_id
                    ),
                    None,
                )
                if body is None:
                    return False
                if hashlib.sha256(body.encode("utf-8")).hexdigest() != _text(target.get("body_sha256")):
                    return False
            return True
        except (KeyError, FileNotFoundError, RuntimeStoreError, StaleRuntimeStateError, TypeError, ValueError):
            return False

    def _target_sections(
        self,
        service: Any,
        project_id: str,
        document: Any,
        *,
        section_ids: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        repo = service.repo
        scope = {
            _text(item) for item in (section_ids or ()) if _text(item)
        } or None
        targets: list[dict[str, Any]] = []
        semantic_nodes = company_template_semantic_node_map()
        for section in document.sections:
            if scope is not None and str(section.section_id) not in scope:
                continue
            if (
                section.applicability_status == "not_applicable"
                or section.applicability_render_action == "omit"
                or section.node_kind not in {"section", "appendix"}
            ):
                continue
            revision, blocks = self._working_copy_blocks(repo, project_id, section)
            writable = _body_blocks(blocks)
            if not writable:
                continue
            body = _body_text(writable)
            if _is_substantive(body):
                continue
            first = writable[0]
            targets.append(
                {
                    "section_id": str(section.section_id),
                    "section_number": str(section.section_number or ""),
                    "heading": str(section.heading or ""),
                    "node_kind": str(section.node_kind or "section"),
                    "template_node_id": str(section.template_node_id or ""),
                    "semantic_node_id": str(
                        semantic_nodes.get(str(section.template_node_id or ""), "")
                    ),
                    "body_block_id": str(first["block_id"]),
                    "expected_revision": revision,
                    "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    "body_text": body,
                }
            )
            if not targets[-1]["semantic_node_id"]:
                raise RuntimeStoreError(
                    f"章节缺少稳定语义节点映射：{section.section_id}"
                )
        return targets

    @staticmethod
    def _available_decision_paths(service: Any, project_id: str) -> set[str]:
        """Return only whole fields that are still awaiting confirmation.

        When a current authoring journey is available, a confirmed field is
        never offered to the chapter generator as a decision target.  This is
        the decisive guard against replacing an established estimand, visit
        strategy, safety endpoint set, or other study fact with a chapter-level
        operational answer.  Lightweight legacy test compositions without an
        authoring journey retain the small curated catalog.
        """
        journey_service = getattr(service, "authoring_journey_service", None)
        if journey_service is None or not journey_service.has_project(project_id):
            return set(FULL_DRAFT_DECISION_FACT_PATHS)
        journey = journey_service.get(project_id)
        definition = getattr(journey, "study_definition", None)
        states = getattr(definition, "field_states", None)
        if not isinstance(states, Mapping):
            return set()
        return {
            path
            for path in FULL_DRAFT_DECISION_FACT_PATHS
            if getattr(states.get(path), "status", "") in {"missing", "deferred"}
        }

    @staticmethod
    def _authoring_journey_binding(service: Any, project_id: str) -> dict[str, Any]:
        journey_service = getattr(service, "authoring_journey_service", None)
        if journey_service is None or not journey_service.has_project(project_id):
            return {}
        journey = journey_service.get(project_id)
        definition = getattr(journey, "study_definition", None)
        if definition is None:
            raise RuntimeStoreError("当前研究设计不存在，全文初稿已停止")
        return {
            "journey_id": str(journey.journey_id),
            "journey_revision": int(journey.revision),
            "study_definition_id": str(definition.definition_id),
            "study_definition_revision": int(definition.revision),
            "study_definition_sha256": str(definition.state_sha256),
            "framing": journey.framing.model_dump(mode="json"),
            "picos": journey.picos.model_dump(mode="json"),
        }

    @staticmethod
    def _decision_path_owners(
        targets: Iterable[Mapping[str, Any]],
        available_paths: Iterable[str],
    ) -> dict[str, str]:
        """Assign each writable decision field to one semantically named section."""
        target_list = list(targets)
        owners: dict[str, str] = {}
        for path in sorted(set(available_paths)):
            patterns = _DECISION_PATH_HEADING_PATTERNS.get(path, ())
            for pattern in patterns:
                match = next(
                    (
                        item
                        for item in target_list
                        if pattern.search(_text(item.get("heading")))
                    ),
                    None,
                )
                if match is not None:
                    owners[path] = _text(match.get("section_id"))
                    break
        return owners

    @staticmethod
    def _chunk_key(chunk: Iterable[Mapping[str, Any]]) -> str:
        return _digest([_text(item.get("section_id")) for item in chunk])

    @staticmethod
    def _source_role(source: AiTaskSourceRef) -> str:
        if source.source_type == "current_project_study_definition":
            return "confirmed_project_facts"
        if source.source_type == "company_protocol_reference_corpus":
            return "company_sop_or_protocol_reference"
        if source.source_type in {
            "shared_protocol_reference_corpus", "shared_phase1_protocol_reference_corpus"
        }:
            return "shared_reference_only"
        return "project_source"

    @classmethod
    def _freeze_reference_source(cls, source: AiTaskSourceRef) -> dict[str, Any]:
        payload = source.model_dump(mode="json")
        text_sha256 = hashlib.sha256(source.text_preview.encode("utf-8")).hexdigest()
        return {
            "source_id": source.source_id,
            "source_version": source.source_entry_id or source.source_id,
            "content_sha256": text_sha256,
            "role": cls._source_role(source),
            "locator": source.locator,
            "source": payload,
        }

    @staticmethod
    def _source_manifest_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
        unique: dict[tuple[str, str], dict[str, Any]] = {}
        for chunk in manifest.get("chunks") or []:
            for item in chunk.get("sources") or []:
                if not isinstance(item, Mapping):
                    continue
                payload = item.get("source") or {}
                key = (_text(item.get("source_id")), _text(item.get("content_sha256")))
                if not all(key):
                    continue
                unique[key] = {
                    "source_id": key[0],
                    "source_version": _text(item.get("source_version")),
                    "content_sha256": key[1],
                    "role": _text(item.get("role")),
                    "source_type": _text(payload.get("source_type")),
                    "title": _text(payload.get("title")),
                    "locator": _text(item.get("locator")),
                }
        sources = sorted(unique.values(), key=lambda item: (
            item["role"], item["title"], item["source_id"]
        ))
        return {
            "schema_version": "protocol-full-draft-source-summary.v1",
            "source_count": len(sources),
            "sources": sources,
        }

    def _live_reference_sources(
        self,
        service: Any,
        project_id: str,
        chunk: list[dict[str, Any]],
    ) -> list[AiTaskSourceRef]:
        """Resolve reference material once, before the durable task exists."""
        protocol = service.repo.protocol(project_id)
        section_by_id = {str(item.section_id): item for item in protocol.sections}
        sources: list[AiTaskSourceRef] = []
        seen: set[str] = set()
        for item in chunk:
            section = section_by_id.get(item["section_id"])
            if section is None:
                raise RuntimeStoreError(f"全文初稿章节不存在：{item['section_id']}")
            source = service._current_project_study_definition_source(protocol, section)
            if source is not None and source.source_id not in seen:
                sources.append(source)
                seen.add(source.source_id)
        if chunk:
            query = " ".join([item["heading"] for item in chunk])
            first_section = section_by_id[chunk[0]["section_id"]]
            for source in [
                *service._company_corpus_sources(
                    protocol, first_section, query, "medical_writing_revision"
                ),
                *service._shared_corpus_sources(
                    protocol, first_section, query, "medical_writing_revision"
                ),
            ]:
                if source.source_id not in seen:
                    sources.append(source)
                    seen.add(source.source_id)
        return sources

    def build_descriptor(
        self,
        project_id: str,
        *,
        section_ids: Iterable[str] | None = None,
        freeze_sources: bool = True,
    ) -> dict[str, Any]:
        service = self._service(project_id)
        repo = service.repo
        document = repo.protocol(project_id)
        scope = sorted({_text(item) for item in (section_ids or ()) if _text(item)})
        targets = self._target_sections(
            service,
            project_id,
            document,
            section_ids=scope,
        )
        if not targets:
            raise RuntimeStoreError(
                "指定章节没有可重新生成的空白正文；请检查章节是否已有实质正文"
                if scope
                else "当前文档没有可生成的空白正文章节；请先检查适用性或已有正文"
            )
        # SMOKE-r1-2 ⑤：按任务自身的 task_type 冻结提交层路由身份
        # （PROTOCOL_FULL_DRAFT→绑定主路 MTPLX，owner 决策 2026-09-28），
        # 不再误用修订任务的云端路由。
        policy = dict(
            service._policy_identity(task_type="protocol_full_draft")
        )
        policy["prompt_version"] = FULL_DRAFT_PROMPT_VERSION
        decision_path_owners = self._decision_path_owners(
            targets,
            self._available_decision_paths(service, project_id),
        )
        descriptor = {
            "descriptor_version": FULL_DRAFT_DESCRIPTOR_VERSION,
            "project_id": project_id,
            "document_id": str(document.document_id),
            "document_version": str(document.version),
            "template_version": str(document.template_version),
            "study_definition": self._binding(repo, project_id, document),
            "authoring_journey": self._authoring_journey_binding(service, project_id),
            "target_sections": targets,
            "prompt_version": FULL_DRAFT_PROMPT_VERSION,
            "minimum_body_chars": FULL_DRAFT_MINIMUM_BODY_CHARS,
            "chunk_size": FULL_DRAFT_CHUNK_SIZE,
            "max_output_tokens": FULL_DRAFT_MAX_OUTPUT_TOKENS,
            "ai_policy": policy,
            "decision_path_owners": decision_path_owners,
        }
        if scope:
            # Only a scoped descriptor carries the key, so every pre-existing
            # full-document descriptor keeps its original digest and job
            # identity.  The scope is part of the digest, so a scoped
            # regeneration can never reuse the full-document job.
            descriptor["section_ids"] = scope
        # This hash protects the editable manuscript, confirmed design and
        # route contract.  The source manifest is frozen separately below so
        # later corpus/library changes do not invalidate an already submitted
        # task or cause it to consume newer bytes mid-run.
        descriptor["execution_context_sha256"] = _digest(descriptor)
        if not freeze_sources:
            return descriptor
        frozen_chunks = []
        for start in range(0, len(targets), FULL_DRAFT_CHUNK_SIZE):
            chunk = targets[start:start + FULL_DRAFT_CHUNK_SIZE]
            frozen_chunks.append({
                "chunk_key": self._chunk_key(chunk),
                "section_ids": [item["section_id"] for item in chunk],
                "sources": [
                    self._freeze_reference_source(source)
                    for source in self._live_reference_sources(service, project_id, chunk)
                ],
            })
        descriptor["source_manifest"] = {
            "schema_version": "protocol-full-draft-source-manifest.v1",
            "chunks": frozen_chunks,
        }
        descriptor["source_manifest_sha256"] = _digest(descriptor["source_manifest"])
        descriptor["digest"] = _digest(descriptor)
        return descriptor

    def submit_durable(
        self,
        project_id: str,
        durable_store: DurableJobStore,
        *,
        actor: str = "medical_manager",
        section_ids: Iterable[str] | None = None,
    ) -> tuple[str, bool]:
        descriptor = self.build_descriptor(project_id, section_ids=section_ids)
        business_key = f"v1:{descriptor['digest']}"
        payload = {
            "descriptor": descriptor,
            "actor": str(actor or "medical_manager"),
        }
        policy = descriptor["ai_policy"]
        request = DurableJobCreateRequest(
            project_id=project_id,
            job_type=FULL_DRAFT_JOB_TYPE,
            business_key=business_key,
            request_hash=descriptor["digest"],
            input_hash=descriptor["digest"],
            payload_json=_canonical(payload),
            created_by=str(actor or "medical_manager"),
            provider=str(policy.get("provider_name") or ""),
            model=str(policy.get("model_name") or ""),
            # R14/R15 evidence: a saturation-window 429 at the synthesis call
            # exhausted a 2-attempt budget and stranded an otherwise healthy
            # 13/21-batch draft (completed batches are preserved, so an
            # extra attempt resumes, it never replays finished work).
            max_attempts=3,
        )
        response = durable_store.create_or_reuse(request)
        return response.job_id, bool(response.reused)

    def _sources_for_chunk(
        self,
        service: Any,
        project_id: str,
        descriptor: dict[str, Any],
        chunk: list[dict[str, Any]],
    ) -> list[AiTaskSourceRef]:
        packet_lines = []
        for item in chunk:
            packet_lines.append(
                "\n".join(
                    [
                        f"SECTION_ID={item['section_id']}",
                        f"章节编号={item['section_number']}",
                        f"章节标题={item['heading']}",
                        f"章节类型={item['node_kind']}",
                        f"当前正文={item['body_text'] or '（当前为空，需生成实质正文）'}",
                    ]
                )
            )
        packet = "\n\n".join(packet_lines)
        packet_id = _digest(
            {
                "descriptor": descriptor["digest"],
                "section_ids": [item["section_id"] for item in chunk],
            }
        )[:24]
        sources: list[AiTaskSourceRef] = [
            AiTaskSourceRef(
                source_id=f"protocol_full_draft_selection:{packet_id}",
                source_type="protocol_full_draft_selection",
                title=f"{descriptor.get('project_id') or project_id} 全文初稿章节包",
                locator=f"document:{descriptor.get('document_id')}:full-draft:{packet_id}",
                text_preview=packet,
                project_id=project_id,
                module="medical_writing",
                source_entry_id=f"full-draft:{descriptor['digest']}:{packet_id}",
            )
        ]
        seen = {sources[0].source_id}
        manifest = descriptor.get("source_manifest") or {}
        if _digest(manifest) != descriptor.get("source_manifest_sha256"):
            raise RuntimeStoreError("全文初稿冻结来源清单完整性校验失败")
        chunk_key = self._chunk_key(chunk)
        frozen = next((item for item in manifest.get("chunks") or []
                       if item.get("chunk_key") == chunk_key), None)
        if frozen is None or frozen.get("section_ids") != [item["section_id"] for item in chunk]:
            raise RuntimeStoreError("全文初稿冻结来源清单与章节范围不一致")
        for item in frozen.get("sources") or []:
            payload = item.get("source") if isinstance(item, Mapping) else None
            if not isinstance(payload, Mapping):
                raise RuntimeStoreError("全文初稿冻结来源条目损坏")
            source = AiTaskSourceRef(**dict(payload))
            if (item.get("source_id") != source.source_id
                    or item.get("locator") != source.locator
                    or item.get("content_sha256") != hashlib.sha256(
                        source.text_preview.encode("utf-8")
                    ).hexdigest()):
                raise RuntimeStoreError("全文初稿冻结来源身份校验失败")
            if source.source_id not in seen:
                sources.append(source)
                seen.add(source.source_id)
        return sources

    @staticmethod
    def _instruction(chunk: list[dict[str, Any]], descriptor: dict[str, Any]) -> str:
        ids = ", ".join(item["section_id"] for item in chunk)
        corpus_rules = "\n".join(
            f"- {rule}" for rule in CORPUS_GENERALIZATION_PROMPT_RULES
        )
        section_ids = {_text(item.get("section_id")) for item in chunk}
        decision_paths = [
            path
            for path, owner in (descriptor.get("decision_path_owners") or {}).items()
            if _text(owner) in section_ids
        ]
        decision_path_text = "、".join(decision_paths) or "（本批次没有可写入的待确认研究字段）"
        return (
            "你是中文临床研究方案撰写专家。请生成一个可直接进入研究方案全文的章节正文候选，"
            "而不是标题清单或提纲。只依据允许来源和当前项目已确认研究事实；公司/共享语料只用于"
            "监管语境措辞与结构，不得继承竞品的药物、人群、剂量、终点、时间点或样本量。"
            f"本批次必须按顺序完整返回这些章节ID：{ids}。每章至少{descriptor['minimum_body_chars']}个中文字符，"
            "必须是连续、可审阅的规范正文，不能使用Markdown表格、TBD/TODO、待补充、‘不适用’泛化句、"
            "‘由方案规定’或重复标题。不得把fixture、ProtocolAssemblyPlan、SECTION_ID、evidence_span_ids等"
            "内部传输/测试标记写入正文；应将事实改写为自然、原生的监管中文。无法安全支持的项目事实不要猜测，"
            "服务器会拒绝不完整或占位内容。对于允许来源已明确给出的年龄、剂量、给药频率、治疗周期、"
            "样本量、终点、量表和访视时间点，必须在对应章节直接写入原值；不得改写成‘将在正式文本中明确’、"
            "‘未提供具体数值’、‘尚无直接证据来源支持’、‘由医学经理/医学负责人确认’或‘确认后再写入’。"
            "来源对数值或结论附有‘仅用于验收’、‘示例’、‘合成’或‘假设参数’等限定时，正文必须保留"
            "该限定，或将该内容移入明确的待确认项；不得把受限信息改写为项目已确认参数。"
            "当前输出就是供医学经理审核的完整候选，不得承诺后续补写；"
            "正文不得出现‘当前项目已确认’、‘本方案不引用竞品’、‘公司语料’、‘章节包’、"
            "‘候选正文’等写作过程说明；这些内容只可转化为rationale中的简洁证据说明。"
            "公司或共享语料不得直接决定本项目的避孕方法、妊娠报告、AE/SAE定义与时限、"
            "剂量调整、合并/禁限用药、洗脱、救援治疗、随机揭盲、分析集或其他研究实施规则。"
            "涉及分析集的章节必须逐集落地成员规则：全分析集（FAS）、安全性分析集（SS）与"
            "符合方案集（PP/PPS）各自给出成员判定与用途；符合方案集的成员判定必须包含"
            "方案偏离排除条款（无重大方案偏离且完成关键评估者入集，重大方案偏离者排除），"
            "不得只写集合名词或把定义推给统计分析计划。"
            "缺少项目实施细节时，必须先完成由已确认事实或允许来源支持的实质正文，并把每个未决事项"
            "写入gap_items；此时content_status使用partial，不得因为局部细节待核对而把已有充分依据的整章留空。"
            "gap_items必须给出稳定gap_id、类别、正文目标位置、下一动作和缺少的来源类别；资料已经存在但"
            "尚未检索到时使用source_not_retrieved，格式或语义节点无法映射时使用mapping_failed，不能误报为用户未上传。"
            "保守正文不得包含命名系统、固定方法清单、固定时限、未经来源支持的角色分工或停止后果。"
            "若允许的当前项目来源没有明确写出某项研究实施规则，不得把该规则写成方案既定要求；"
            "妊娠处理、AE分类、报告对象与时限、随访终点、数据职责、签署要求和CRF记录方式等"
            "只能说明本章节应覆盖的目的与范围，并把可选建议写入rationale，不能在正文中虚构为已决定事项。"
            "proposal_text必须是可以直接写入方案的规范句子，不得用‘本章节需要覆盖’、‘本节应列明’、"
            "‘本章节说明目的与范围’等目录说明冒充正文。不得由已有访视日推断实验室检查、生命体征、"
            "心电图、体格检查或依从性评价在每个访视都实施；不得由终点中的‘较基线变化’自行新增"
            "DLQI采集时点；不得自行定义TEAE采集窗口、研究结束时点或安全性评估窗口。"
            "妊娠或哺乳期排除不能推出避孕方法、伴侣妊娠报告、新生儿随访或妊娠检查日程。"
            "下列章节采用更严格的来源判定：方案概要必须用已确认设计事实完成，并省略未确认实施细节；"
            "疾病背景及治疗现状在缺少流行病学、疾病负担、指南或治疗现状来源时必须source_gap；"
            "筛选失败与重新筛选、计划外访视、剂量调整/暂停/恢复/永久停药、药物过量与给药错误、"
            "试验药包装储存与发放回收、AE/SAE/SUSAR定义与采集报告、研究药物具体风险、保险赔偿，"
            "在缺少对应项目文件时必须source_gap，不能用条件句、范围句或通用原则标成complete。"
            "盲法章节只能写双盲、1:1和匹配安慰剂等已确认事实，不得自行指定受试者、研究者、"
            "评价者或其他人员的盲态范围。"
            "除方案概要、研究设计、目的终点和样本量章节外，不要重复整套样本量、剂量、主要终点、"
            "随机和盲法信息，只写与本章节直接相关的事实。"
            "每章用evidence_span_ids绑定本次evidence_spans中的直接依据，并将needs_medical_confirmation设为true。"
            "每章还必须返回content_status、decision_items和missing_source_classes。"
            "事实充分时用complete并返回完整正文。只有本批次列出的待确认研究字段能够完整承载一个"
            "研究设计决定时才可用decision_required：给出一个推荐项和1至2个备选项，并将proposal_text"
            "严格留空；用户确认前不得输出任何预选正文。若缺少的实施规则没有对应的待确认研究字段，"
            "必须用source_gap说明所缺项目来源或职能确认，不能借用语义不相干的字段。缺少IB、既往研究、"
            "流行病学、研究药物作用机制/非临床/既往临床资料等核心来源缺失，导致本章无法形成任何"
            "有实质信息的正文时，才用source_gap；proposal_text留空并准确列出缺少的来源类别，禁止用"
            "通用段落凑足字数。量表名称、终点及评价时点已有项目事实时，应先写入这些已确认内容，"
            "把版本、授权和培训等待核细节列入rationale，不得把整章降为空白。每个决定项的fact_path只能从以下字段中按语义选择并原样复制："
            f"{decision_path_text}。不得自造字段路径；同一字段最多返回一个决定项。决定项只用于引导上游研究设计确认，"
            "模型本身不得写回研究事实。决定项的每个选项都必须是用户点选后可直接写入对应研究字段的"
            "具体答案；如果来源不足以提出具体、互斥且可执行的选项，必须返回source_gap，不能用‘按类别列出’、"
            "‘由团队确认’或其他写作方式选择冒充科学决定。"
            "探索性目的与终点的选项必须包含‘本研究不设置探索性目的/终点’，不能强迫确证性研究新增"
            "探索程序；目的和终点的推荐必须能够成对对应。"
            "\n语料泛化规则（全部适用）：\n"
            f"{corpus_rules}"
        )

    @staticmethod
    def _review_policy(heading: str, proposal: str, corpus_count: int) -> dict[str, Any]:
        required_reasons: list[str] = []
        advisory_reasons: list[str] = []
        heading_signals = sorted(
            {
                match.group(0)
                for match in _REQUIRED_REVIEW_HEADING_RE.finditer(heading)
            }
        )
        embedded_signals = sorted(
            {match.group(0) for match in _REQUIRED_REVIEW_CONTENT_RE.finditer(proposal)}
        )
        if heading_signals:
            advisory_reasons.append(
                f"本节复述高影响研究设计（{'、'.join(heading_signals[:6])}）；请在合并设计摘要中统一核对。"
            )
        if embedded_signals:
            advisory_reasons.append(
                f"本节提及高影响设计信息（{'、'.join(embedded_signals[:6])}）；系统未把重复提及升级为强制确认。"
            )
        if corpus_count and _CORPUS_CONDUCT_RE.search(proposal):
            advisory_reasons.append(
                "本节引用公司语料形成共性表述；定稿时请用本项目权威文件复核适用性。"
            )
        restatement_count = sum(
            bool(pattern.search(proposal)) for pattern in _DESIGN_RESTATEMENT_SIGNALS
        )
        if (
            restatement_count >= 3
            and not _DESIGN_RESTATEMENT_ALLOWED_HEADING_RE.search(heading)
        ):
            advisory_reasons.append(
                "本节重复了多项总体设计事实；建议压缩为与本节直接相关的信息。"
            )
        return {
            "review_level": "required" if required_reasons else "standard",
            "review_reasons": required_reasons,
            "review_advisories": advisory_reasons,
        }

    @staticmethod
    def _source_qualification_advisories(
        proposal: str,
        evidence_quotes: Iterable[str],
    ) -> list[str]:
        source_markers = sorted(
            {
                match.group(0)
                for quote in evidence_quotes
                for match in _SOURCE_QUALIFICATION_RE.finditer(_text(quote))
            }
        )
        if not source_markers or _SOURCE_QUALIFICATION_RE.search(proposal):
            return []
        return [
            "本节依据含明确的受限使用标记（"
            f"{'、'.join(source_markers[:4])}），但候选正文未保留；"
            "请勿将相关数值或结论视为项目已确认信息。"
        ]

    @classmethod
    def _review_metadata(
        cls,
        section: Mapping[str, Any],
        output: Mapping[str, Any],
        sources: list[AiTaskSourceRef],
        descriptor_section: Mapping[str, Any],
    ) -> dict[str, Any]:
        evidence_by_id = {
            str(item.get("span_id") or ""): item
            for item in output.get("evidence_spans") or []
            if isinstance(item, dict) and str(item.get("span_id") or "").strip()
        }
        source_by_id = {source.source_id: source for source in sources}
        referenced_sources = []
        for span_id in section.get("evidence_span_ids") or []:
            evidence = evidence_by_id.get(str(span_id))
            source = source_by_id.get(str((evidence or {}).get("source_id") or ""))
            if source is not None:
                referenced_sources.append(source)
        project_count = sum(
            source.source_type == "current_project_study_definition"
            for source in referenced_sources
        )
        corpus_count = sum(
            source.source_type in _CORPUS_SOURCE_TYPES for source in referenced_sources
        )
        metadata = cls._review_policy(
            _text(descriptor_section.get("heading")),
            _text(section.get("proposal_text")),
            corpus_count,
        )
        evidence_review_advisories = cls._source_qualification_advisories(
            _text(section.get("proposal_text")),
            (
                _text(evidence_by_id.get(str(span_id), {}).get("quote"))
                for span_id in section.get("evidence_span_ids") or []
            ),
        )
        metadata["evidence_review_advisories"] = evidence_review_advisories
        metadata["review_advisories"] = [
            *metadata["review_advisories"],
            *evidence_review_advisories,
        ]
        metadata.update(
            {
            "evidence_summary": {
                "project_fact_spans": project_count,
                "corpus_spans": corpus_count,
            },
            }
        )
        return metadata

    @staticmethod
    def _evidence_bindings_for_section(
        section: Mapping[str, Any],
        output: Mapping[str, Any],
    ) -> list[dict[str, str]]:
        """Persist the exact evidence behind one section without cross-run ID collisions.

        ``span_id`` values are scoped to one provider response and may repeat in
        another chunk.  Keeping each binding beside its section makes the
        persisted candidate independently auditable while preserving the
        provider's original evidence IDs for display and diagnostics.
        """
        evidence_by_id = {
            _text(item.get("span_id")): item
            for item in output.get("evidence_spans") or []
            if isinstance(item, Mapping) and _text(item.get("span_id"))
        }
        bindings: list[dict[str, str]] = []
        for raw_span_id in section.get("evidence_span_ids") or []:
            span_id = _text(raw_span_id)
            evidence = evidence_by_id.get(span_id)
            if evidence is None:
                raise RuntimeStoreError(f"章节证据引用无法解析：{span_id or 'empty'}")
            binding = {
                "span_id": span_id,
                "source_id": _text(evidence.get("source_id")),
                "locator": _text(evidence.get("locator")),
                "quote": _text(evidence.get("quote")),
            }
            if not all(binding.values()):
                raise RuntimeStoreError(f"章节证据绑定不完整：{span_id}")
            binding["quote_sha256"] = hashlib.sha256(
                binding["quote"].encode("utf-8")
            ).hexdigest()
            bindings.append(binding)
        return bindings

    @staticmethod
    def _section_evidence_is_resolvable(
        section: Mapping[str, Any],
        source_locators: Mapping[str, str],
    ) -> bool:
        expected = [_text(item) for item in section.get("evidence_span_ids") or []]
        bindings = section.get("evidence_bindings")
        if not isinstance(bindings, list):
            return False
        section_source_ids = {
            _text(item) for item in section.get("source_ids") or [] if _text(item)
        }
        actual: list[str] = []
        for item in bindings:
            if not isinstance(item, Mapping):
                return False
            span_id = _text(item.get("span_id"))
            source_id = _text(item.get("source_id"))
            locator = _text(item.get("locator"))
            quote = _text(item.get("quote"))
            if (
                not span_id
                or source_id not in section_source_ids
                or source_locators.get(source_id) != locator
                or not locator
                or not quote
                or _text(item.get("quote_sha256"))
                != hashlib.sha256(quote.encode("utf-8")).hexdigest()
            ):
                return False
            actual.append(span_id)
        return actual == expected

    @classmethod
    def _artifact_evidence_is_resolvable(cls, artifact: Mapping[str, Any]) -> bool:
        source_locators: dict[str, str] = {}
        for item in artifact.get("source_bindings") or []:
            if not isinstance(item, Mapping):
                return False
            source_id = _text(item.get("source_id"))
            locator = _text(item.get("locator"))
            if not source_id or not locator:
                return False
            if source_id in source_locators and source_locators[source_id] != locator:
                return False
            source_locators[source_id] = locator
        sections = artifact.get("sections")
        return isinstance(sections, list) and bool(sections) and all(
            isinstance(section, Mapping)
            and cls._section_evidence_is_resolvable(section, source_locators)
            for section in sections
        )

    @classmethod
    def _apply_review_policy(cls, artifact: dict[str, Any]) -> dict[str, Any]:
        required_ids: list[str] = []
        decision_ids: list[str] = []
        source_gap_ids: list[str] = []
        partial_ids: list[str] = []
        for section in artifact.get("sections") or []:
            content_status = _text(section.get("content_status")) or "complete"
            if content_status == "decision_required":
                section.update({
                    "review_level": "blocked",
                    "review_reasons": ["本节包含尚未确认的科学决定；请先在研究设计中选择推荐项或备选项。"],
                    "review_advisories": [],
                })
                decision_ids.append(_text(section.get("section_id")))
                continue
            if content_status == "source_gap":
                section.update({
                    "review_level": "blocked",
                    "review_reasons": ["本节缺少可引用来源；补充所列资料后再生成正文。"],
                    "review_advisories": [],
                })
                source_gap_ids.append(_text(section.get("section_id")))
                continue
            if content_status == "partial":
                partial_ids.append(_text(section.get("section_id")))
            evidence_summary = section.get("evidence_summary") or {}
            evidence_review_advisories = list(
                section.get("evidence_review_advisories") or []
            )
            section.update(
                cls._review_policy(
                    _text(section.get("heading")),
                    _text(section.get("proposal_text")),
                    int(evidence_summary.get("corpus_spans") or 0),
                )
            )
            section["evidence_review_advisories"] = evidence_review_advisories
            section["review_advisories"] = [
                *section["review_advisories"],
                *evidence_review_advisories,
            ]
            if section.get("review_level") == "required":
                required_ids.append(_text(section.get("section_id")))
        coverage = artifact.setdefault("coverage", {})
        coverage["required_review_count"] = len(required_ids)
        coverage["required_review_section_ids"] = required_ids
        coverage["decision_required_count"] = len(decision_ids)
        coverage["decision_required_section_ids"] = decision_ids
        coverage["source_gap_count"] = len(source_gap_ids)
        coverage["source_gap_section_ids"] = source_gap_ids
        coverage["partial_count"] = len(partial_ids)
        coverage["partial_section_ids"] = partial_ids
        is_legacy = artifact.get("schema_version") in LEGACY_FULL_DRAFT_ARTIFACT_SCHEMAS
        evidence_chain_resolvable = (
            not is_legacy and cls._artifact_evidence_is_resolvable(artifact)
        )
        coverage["legacy_read_only"] = is_legacy
        coverage["evidence_chain_resolvable"] = evidence_chain_resolvable
        coverage["working_draft_ready"] = (
            evidence_chain_resolvable
            and any(_text(item.get("proposal_text")) for item in artifact.get("sections") or [])
        )
        coverage["formal_ready"] = (
            evidence_chain_resolvable and not decision_ids and not source_gap_ids
            and not partial_ids
        )
        coverage["adoption_ready"] = coverage["formal_ready"]
        artifact["review_policy_version"] = FULL_DRAFT_REVIEW_POLICY_VERSION
        return artifact

    @staticmethod
    def _run_output(run: Any) -> dict[str, Any]:
        for artifact in reversed(list(getattr(run, "artifacts", []) or [])):
            payload = getattr(artifact, "payload", None)
            if isinstance(payload, dict) and "full_draft" in payload:
                return payload
        raise RuntimeStoreError("全文初稿 AI 运行结果缺少可持久化的 full_draft 输出")

    def _artifact_path(
        self,
        project_id: str,
        job_id: str,
        filename: str,
        *,
        chunk: Optional[list[dict[str, Any]]] = None,
        descriptor_digest: str = "",
    ) -> Path:
        if chunk is None:
            relative = Path(_safe_project_path(project_id)) / job_id / filename
        else:
            chunk_digest = _digest(
                {
                    "descriptor": descriptor_digest,
                    "section_ids": [item["section_id"] for item in chunk],
                }
            )[:24]
            relative = (
                Path(_safe_project_path(project_id))
                / job_id
                / "chunks"
                / f"{filename}-{chunk_digest}.json"
            )
        return self.artifact_root / relative

    @staticmethod
    def _read_json_file(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = _canonical(payload).encode("utf-8")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return hashlib.sha256(encoded).hexdigest()

    def _read_reusable_chunk(
        self,
        project_id: str,
        job_id: str,
        descriptor: dict[str, Any],
        chunk_index: int,
        chunk: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        path = self._artifact_path(
            project_id,
            job_id,
            f"chunk-{chunk_index:04d}",
            chunk=chunk,
            descriptor_digest=str(descriptor.get("digest") or ""),
        )
        payload = self._read_json_file(path)
        if not payload:
            return None
        expected_ids = [item["section_id"] for item in chunk]
        if (
            payload.get("schema_version") != FULL_DRAFT_CHUNK_ARTIFACT_SCHEMA
            or payload.get("job_id") != job_id
            or payload.get("project_id") != project_id
            or payload.get("precondition_digest") != descriptor.get("digest")
            or payload.get("chunk_index") != chunk_index
            or payload.get("section_ids") != expected_ids
        ):
            return None
        sections = payload.get("sections")
        if not isinstance(sections, list):
            return None
        actual_ids = [
            str(item.get("section_id") or "")
            for item in sections
            if isinstance(item, dict)
        ]
        if actual_ids != expected_ids:
            return None
        source_locators = {
            _text(item.get("source_id")): _text(item.get("locator"))
            for item in payload.get("source_bindings") or []
            if isinstance(item, Mapping)
            and _text(item.get("source_id"))
            and _text(item.get("locator"))
        }
        if not all(
            self._section_evidence_is_resolvable(item, source_locators)
            for item in sections
            if isinstance(item, Mapping)
        ):
            return None
        return payload

    def _execute_chunk(
        self,
        service: Any,
        project_id: str,
        descriptor: dict[str, Any],
        chunk: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], Any, list[AiTaskSourceRef]]:
        sources = self._sources_for_chunk(service, project_id, descriptor, chunk)
        chunk_section_ids = {item["section_id"] for item in chunk}
        decision_fact_paths = [
            path
            for path, owner in (descriptor.get("decision_path_owners") or {}).items()
            if owner in chunk_section_ids
        ]
        context = {
            "draft_version": descriptor["digest"],
            "section_ids": [item["section_id"] for item in chunk],
            "marker_open": "SECTION_ID=",
            "marker_close": "\n",
            "minimum_body_chars": descriptor["minimum_body_chars"],
            "decision_fact_paths": decision_fact_paths,
        }
        run = service.ai_task_runner.submit_internal(
            project_id,
            AiTaskRequest(
                module="medical_writing",
                task_type=AiTaskType.PROTOCOL_FULL_DRAFT,
                prompt_version=FULL_DRAFT_PROMPT_VERSION,
                allowed_sources=sources,
                forbidden_source_ids=[],
                user_instruction=self._instruction(chunk, descriptor),
                task_context=context,
            ),
        )
        if run.status == AiTaskRunStatus.BLOCKED:
            raise RuntimeStoreError("独立AI未配置，未生成全文初稿候选")
        if run.status == AiTaskRunStatus.FAILED:
            detail = "; ".join(getattr(run, "validation_errors", []) or []) or getattr(run, "error_message", "")
            raise RuntimeStoreError(f"独立AI全文初稿未通过校验：{detail or 'provider output failed validation'}")
        output = self._run_output(run)
        sections = ((output.get("full_draft") or {}).get("sections") or [])
        expected_ids = [item["section_id"] for item in chunk]
        actual_ids = [str(item.get("section_id") or "") for item in sections if isinstance(item, dict)]
        if actual_ids != expected_ids:
            raise RuntimeStoreError("全文初稿章节身份或顺序不匹配，未写入任何正文")
        # P0-A（NEW-13 根治）：同批跨节重复正文确定性拒收——消息含『未通过
        # 校验』落入既有 validation 重试预算；重试仍犯→批次跳过并点名
        # （run_job 的 skipped_chunks 记录 section_ids + reason）。
        duplicates = find_full_draft_duplicate_sections(sections)
        if duplicates:
            raise RuntimeStoreError(
                "全文初稿跨节正文重复未通过校验（同一正文出现于多节，未写入任何正文）："
                + _duplicate_section_names(duplicates)
            )
        return output, run, sources

    @staticmethod
    def _run_route_receipt(run: Any) -> dict[str, Any]:
        return {
            "ai_run_id": _text(getattr(run, "run_id", "")),
            "provider": _text(getattr(run, "provider", "")),
            "model": _text(getattr(run, "model_name", "")),
            "route_profile_id": _text(getattr(run, "route_profile_id", "")),
            "route_identity_hash": _text(getattr(run, "route_identity_hash", "")),
            "route_base_url": _text(getattr(run, "route_base_url", "")),
            "expected_response_model": _text(
                getattr(run, "expected_response_model", "")
            ),
            "actual_response_model": _text(
                getattr(run, "actual_response_model", "")
            ),
            "thinking": _text(getattr(run, "route_thinking", "")),
            "reasoning_effort": _text(getattr(run, "route_reasoning_effort", "")),
            "fallback_chain_id": _text(getattr(run, "fallback_chain_id", "")),
            "fallback_depth": int(getattr(run, "fallback_depth", 0) or 0),
            "fallback_reason": _text(getattr(run, "fallback_reason", "")),
        }

    @staticmethod
    def _result_route_identity(
        receipts: list[dict[str, Any]],
        fallback_policy: Mapping[str, Any],
    ) -> tuple[str, str]:
        identities = {
            (_text(item.get("provider")), _text(item.get("model")))
            for item in receipts
            if _text(item.get("provider")) or _text(item.get("model"))
        }
        if len(identities) == 1:
            return next(iter(identities))
        if len(identities) > 1:
            return "mixed", "mixed"
        return (
            _text(fallback_policy.get("provider_name")),
            _text(fallback_policy.get("model_name")),
        )

    def run_job(
        self,
        job: Any,
        claim_token: str,
        cancel_check: Callable[[], bool],
        heartbeat: Callable[[DurableJobProgressPayload], bool],
    ) -> DurableJobResult:
        payload = json.loads(job.payload_json or "{}")
        expected = payload.get("descriptor") or {}
        service = self._service(job.project_id)
        try:
            current = self.build_descriptor(
                job.project_id,
                section_ids=expected.get("section_ids"),
                freeze_sources=False,
            )
        except Exception as exc:
            return DurableJobResult(error=f"全文初稿上下文不可用：{exc}", retryable=False)
        if (current.get("execution_context_sha256")
                != expected.get("execution_context_sha256")):
            return DurableJobResult(error="全文初稿上下文已变化，请重新生成候选", retryable=False)
        expected_policy = (expected.get("ai_policy") or {}).get("route_identity_hash")
        # SMOKE-r1-2 ⑤：比较基准同样按 PROTOCOL_FULL_DRAFT 的任务级路由解析，
        # 与 build_descriptor 的冻结口径一致。
        current_policy = service._policy_identity(
            task_type="protocol_full_draft"
        )
        if expected_policy != current_policy.get("route_identity_hash"):
            return DurableJobResult(error="独立AI路由身份已变化，请重新生成全文初稿", retryable=False)

        target = list(expected.get("target_sections") or [])
        chunk_size = max(1, int(expected.get("chunk_size") or FULL_DRAFT_CHUNK_SIZE))
        chunks = [
            target[index : index + chunk_size]
            for index in range(0, len(target), chunk_size)
        ]
        final_path = self._artifact_path(job.project_id, job.job_id, "full-draft.json")
        existing_final = self._read_json_file(final_path)
        if (
            existing_final
            and existing_final.get("schema_version") == FULL_DRAFT_ARTIFACT_SCHEMA
            and existing_final.get("job_id") == job.job_id
            and existing_final.get("project_id") == job.project_id
            and existing_final.get("precondition_digest") == expected.get("digest")
            and (existing_final.get("coverage") or {}).get("section_ids")
            == [item["section_id"] for item in target]
            and self._artifact_evidence_is_resolvable(existing_final)
        ):
            encoded = _canonical(existing_final).encode("utf-8")
            artifact_sha = hashlib.sha256(encoded).hexdigest()
            relative = final_path.relative_to(self.artifact_root)
            locator = _canonical(
                {
                    "schema_version": FULL_DRAFT_ARTIFACT_SCHEMA,
                    "artifact_relpath": relative.as_posix(),
                    "artifact_sha256": artifact_sha,
                    "precondition_digest": expected["digest"],
                    # section_ids 列表随章节增长，会把 locator 撑破
                    # DurableJobRecord.artifact_locator 的 2000 字符上限；
                    # 定位器只需要路径与哈希，覆盖明细保留在工件内。
                    "coverage": {
                        key: value
                        for key, value in (existing_final.get("coverage") or {}).items()
                        if key != "section_ids"
                    },
                }
            )
            provider, model = self._result_route_identity(
                list(existing_final.get("ai_route_receipts") or []),
                expected.get("ai_policy") or {},
            )
            return DurableJobResult(
                output_hash=artifact_sha,
                artifact_locator=locator,
                provider=provider,
                model=model,
                progress=DurableJobProgressPayload(
                    phase="persisted_candidate",
                    percent=1.0,
                    step=len(chunks),
                    step_total=len(chunks),
                    message=f"已复用已持久化全文初稿 {len(target)}/{len(target)} 个章节候选",
                ),
            )
        all_sections: list[dict[str, Any]] = []
        skipped_chunks: list[dict[str, Any]] = []
        run_ids: list[str] = []
        route_receipts: list[dict[str, Any]] = []
        source_bindings: list[dict[str, Any]] = []
        total = len(chunks)
        for index, chunk in enumerate(chunks, start=1):
            if cancel_check():
                return DurableJobResult(error="全文初稿任务已取消或失去执行权", retryable=False)
            progress = DurableJobProgressPayload(
                phase="calling_synthesis_ai",
                percent=(index - 1) / max(total, 1),
                step=index,
                step_total=total,
                message=f"正在生成全文初稿（第 {index}/{total} 批）",
            )
            if not heartbeat(progress):
                return DurableJobResult(error="全文初稿任务失去执行权", retryable=True)
            reusable = self._read_reusable_chunk(
                job.project_id,
                job.job_id,
                expected,
                index,
                chunk,
            )
            if reusable is not None:
                run_ids.append(str(reusable.get("ai_run_id") or ""))
                reusable_receipt = reusable.get("ai_route")
                if isinstance(reusable_receipt, dict):
                    route_receipts.append(dict(reusable_receipt))
                else:
                    frozen_policy = expected.get("ai_policy") or {}
                    frozen_snapshot = (
                        frozen_policy.get("route_identity_snapshot") or {}
                    )
                    route_receipts.append(
                        {
                            "ai_run_id": _text(reusable.get("ai_run_id")),
                            "provider": _text(
                                frozen_policy.get("provider")
                                or frozen_policy.get("provider_name")
                            ),
                            "model": _text(
                                frozen_policy.get("model")
                                or frozen_policy.get("model_name")
                            ),
                            "route_profile_id": _text(
                                frozen_policy.get("route_profile_id")
                                or frozen_snapshot.get("profile_id")
                            ),
                            "route_identity_hash": _text(
                                frozen_policy.get("route_identity_hash")
                                or frozen_policy.get("identity_sha256")
                            ),
                            "route_base_url": _text(
                                frozen_policy.get("base_url")
                                or frozen_snapshot.get("base_url")
                            ),
                            "expected_response_model": _text(
                                frozen_policy.get("required_response_model")
                                or frozen_snapshot.get("expected_response_model")
                                or frozen_policy.get("model")
                                or frozen_policy.get("model_name")
                            ),
                            "actual_response_model": "",
                            "thinking": _text(
                                frozen_policy.get("thinking")
                                or frozen_snapshot.get("thinking")
                            ),
                            "reasoning_effort": _text(
                                frozen_policy.get("reasoning_effort")
                                or frozen_snapshot.get("reasoning_effort")
                            ),
                            "fallback_chain_id": "",
                            "fallback_depth": 0,
                            "fallback_reason": "",
                            "legacy_inferred": True,
                            "identity_evidence": "legacy_inferred",
                        }
                    )
                source_bindings.extend(
                    item
                    for item in reusable.get("source_bindings") or []
                    if isinstance(item, dict)
                )
                all_sections.extend(
                    dict(item)
                    for item in reusable.get("sections") or []
                    if isinstance(item, dict)
                )
            else:
                # SMOKE-r2-3 ⑤：校验类失败（模型输出格式抖动）整批重请求，
                # 最多 FULL_DRAFT_CHUNK_ATTEMPTS 次。R6 片B′（P0-25）：容量类
                # （提供方507/5xx/空回包/梯级预算耗尽）纳入同一重试预算
                # （1次执行+≤2次重试）；预算耗尽后跳过该批并标记，其余批次
                # 照常产出候选（可稍后“续跑”补齐）。确定性失败保持 fail-fast。
                output = run = sources = None
                chunk_error: Exception | None = None
                chunk_failure_class = "deterministic"
                for attempt in range(1, FULL_DRAFT_CHUNK_ATTEMPTS + 1):
                    # R8 片Z（P1-45）：批级心跳≤60秒——单批AI调用2~9.5分钟
                    # 期间作业行不再静默（现场：末批20分钟无心跳须用户自行
                    # 刷新）。执行期间由看护线程持续续约；末批/校验重试附
                    # 已耗时（分钟）。
                    chunk_started = time.monotonic()
                    keepalive_stop = threading.Event()
                    keepalive_lost = threading.Event()

                    def _keepalive() -> None:
                        while not keepalive_stop.wait(FULL_DRAFT_HEARTBEAT_INTERVAL_SECONDS):
                            elapsed_minutes = (time.monotonic() - chunk_started) / 60.0
                            if not heartbeat(
                                DurableJobProgressPayload(
                                    phase="calling_synthesis_ai",
                                    percent=(index - 1) / max(total, 1),
                                    step=index,
                                    step_total=total,
                                    message=(
                                        f"第 {index}/{total} 批仍在生成中（已 {elapsed_minutes:.0f} 分钟）"
                                        + (f"；末批校验中（已 {elapsed_minutes:.0f} 分钟）"
                                           if index == total and attempt > 1 else "")
                                    ),
                                )
                            ):
                                keepalive_lost.set()
                                return

                    keepalive = threading.Thread(target=_keepalive, daemon=True)
                    keepalive.start()
                    try:
                        output, run, sources = self._execute_chunk(
                            service, job.project_id, expected, chunk
                        )
                        chunk_error = None
                        break
                    except Exception as exc:
                        chunk_error = exc
                        chunk_failure_class = classify_full_draft_chunk_failure(exc)
                        if chunk_failure_class == "deterministic":
                            # 确定性失败：保持 fail-fast 原语义
                            return DurableJobResult(
                                error=str(exc), retryable=False
                            )
                        if attempt < FULL_DRAFT_CHUNK_ATTEMPTS:
                            if chunk_failure_class == "capacity":
                                # 提供方层已跑完自己的退避梯；批次层再等待
                                # 一小段（1s/2s）即再试，不阻塞其他批次。
                                time.sleep(min(2.0, float(attempt)))
                            if not heartbeat(
                                DurableJobProgressPayload(
                                    phase="calling_synthesis_ai",
                                    percent=(index - 1) / max(total, 1),
                                    step=index,
                                    step_total=total,
                                    message=(
                                        f"第 {index}/{total} 批"
                                        + ("输出未通过校验，正在重新请求" if chunk_failure_class == "validation" else "遇到服务繁忙，稍候自动重试")
                                        + f"（第 {attempt + 1} 次尝试，已 {(time.monotonic() - chunk_started) / 60.0:.0f} 分钟）"
                                    ),
                                )
                            ):
                                return DurableJobResult(
                                    error="全文初稿任务失去执行权",
                                    retryable=True,
                                )
                    finally:
                        keepalive_stop.set()
                        keepalive.join(timeout=1.0)
                    if keepalive_lost.is_set():
                        return DurableJobResult(
                            error="全文初稿任务失去执行权",
                            retryable=True,
                        )
                if chunk_error is not None:
                    # R6 片B′：重试预算耗尽→跳过并标记，不弃整单。
                    skipped_chunks.append({
                        "chunk_index": index,
                        "section_ids": [item["section_id"] for item in chunk],
                        "reason": str(chunk_error),
                        "failure_class": chunk_failure_class,
                        "attempts": FULL_DRAFT_CHUNK_ATTEMPTS,
                    })
                    if not heartbeat(
                        DurableJobProgressPayload(
                            phase="calling_synthesis_ai",
                            percent=(index - 1) / max(total, 1),
                            step=index,
                            step_total=total,
                            message=(
                                f"第 {index}/{total} 批连续失败已跳过"
                                f"（{'服务繁忙' if chunk_failure_class == 'capacity' else '输出未通过校验'}），"
                                "其余批次继续；完成后可单独续跑补齐该批"
                            ),
                        )
                    ):
                        return DurableJobResult(
                            error="全文初稿任务失去执行权",
                            retryable=True,
                        )
                    continue
                if cancel_check():
                    return DurableJobResult(error="AI完成后任务已取消，未持久化全文候选", retryable=False)
                chunk_source_bindings = [
                    {
                        "source_id": source.source_id,
                        "source_type": source.source_type,
                        "source_version": source.source_entry_id or source.source_id,
                        "role": (
                            "current_working_draft_packet"
                            if source.source_type == "protocol_full_draft_selection"
                            else self._source_role(source)
                        ),
                        "locator": source.locator,
                        "content_sha256": hashlib.sha256(
                            source.text_preview.encode("utf-8")
                        ).hexdigest(),
                        # Legacy read compatibility for v5-v9 evidence readers.
                        "text_sha256": hashlib.sha256(
                            source.text_preview.encode("utf-8")
                        ).hexdigest(),
                    }
                    for source in sources
                ]
                chunk_sections = []
                chunk_by_id = {item["section_id"]: item for item in chunk}
                for item in (output.get("full_draft") or {}).get("sections") or []:
                    section = dict(item)
                    descriptor_section = chunk_by_id.get(str(section.get("section_id") or ""), {})
                    section["heading"] = descriptor_section.get("heading", "")
                    section["section_number"] = descriptor_section.get("section_number", "")
                    section["ai_run_id"] = str(run.run_id)
                    section["source_ids"] = [source.source_id for source in sources]
                    try:
                        section["evidence_bindings"] = self._evidence_bindings_for_section(
                            section,
                            output,
                        )
                    except RuntimeStoreError as exc:
                        return DurableJobResult(error=str(exc), retryable=False)
                    section.update(
                        self._review_metadata(
                            section,
                            output,
                            sources,
                            descriptor_section,
                        )
                    )
                    chunk_sections.append(section)
                chunk_record = {
                    "schema_version": FULL_DRAFT_CHUNK_ARTIFACT_SCHEMA,
                    "job_id": job.job_id,
                    "project_id": job.project_id,
                    "precondition_digest": expected["digest"],
                    "chunk_index": index,
                    "section_ids": [item["section_id"] for item in chunk],
                    "sections": chunk_sections,
                    "ai_run_id": str(run.run_id),
                    "ai_route": self._run_route_receipt(run),
                    "source_bindings": chunk_source_bindings,
                }
                try:
                    self._write_json_atomic(
                        self._artifact_path(
                            job.project_id,
                            job.job_id,
                            f"chunk-{index:04d}",
                            chunk=chunk,
                            descriptor_digest=expected["digest"],
                        ),
                        chunk_record,
                    )
                except Exception as exc:
                    return DurableJobResult(error=f"全文初稿分批候选持久化失败：{exc}", retryable=False)
                run_ids.append(str(run.run_id))
                route_receipts.append(self._run_route_receipt(run))
                source_bindings.extend(chunk_source_bindings)
                all_sections.extend(chunk_sections)
            if not heartbeat(
                DurableJobProgressPayload(
                    phase="validating_candidates",
                    percent=index / max(total, 1),
                    step=index,
                    step_total=total,
                    message=f"已完成全文初稿第 {index}/{total} 批校验",
                )
            ):
                return DurableJobResult(error="全文初稿校验后任务失去执行权", retryable=True)

        expected_ids = [item["section_id"] for item in target]
        actual_ids = [str(item.get("section_id") or "") for item in all_sections]
        # R6 片B′：被跳过批次的章节不计入覆盖缺口；未跳过而缺失仍是硬错误。
        skipped_section_ids = {
            section_id
            for record in skipped_chunks
            for section_id in record.get("section_ids") or []
        }
        expected_after_skip = [
            section_id
            for section_id in expected_ids
            if section_id not in skipped_section_ids
        ]
        if not all_sections and skipped_chunks:
            # 全部批次均失败：不落空工件，保持可续跑语义（resume 会跳过
            # 已持久化批次、重跑失败批次）。
            return DurableJobResult(
                error=(
                    f"全部批次均未产出（{len(skipped_chunks)} 批重试后仍失败，"
                    "原因见进度消息）；任务保持可续跑，稍后可再试"
                ),
                retryable=True,
            )
        if actual_ids != expected_after_skip:
            return DurableJobResult(error="全文初稿合并后章节覆盖不完整，未写入任何正文", retryable=False)
        if not self._artifact_evidence_is_resolvable(
            {"sections": all_sections, "source_bindings": source_bindings}
        ):
            return DurableJobResult(error="全文初稿章节证据链不完整，未写入候选", retryable=False)
        decision_path_owners = expected.get("decision_path_owners") or {}
        seen_decision_paths: set[str] = set()
        for section in all_sections:
            section_id = _text(section.get("section_id"))
            for item in section.get("decision_items") or []:
                fact_path = _text(item.get("fact_path"))
                if decision_path_owners.get(fact_path) != section_id:
                    return DurableJobResult(
                        error=f"全文初稿决定字段未由指定章节承载：{fact_path or 'empty'}",
                        retryable=False,
                    )
                if fact_path in seen_decision_paths:
                    return DurableJobResult(
                        error=f"全文初稿决定字段重复：{fact_path}",
                        retryable=False,
                    )
                seen_decision_paths.add(fact_path)
        # NEW-14/44 内容族③（R27 第3轮修订）：统计章样本量算术自洽校验。
        # R9（第8轮末修订动作2）P0-18 生成层护栏②：不自洽节的声明数字
        # 不得照抄——不一致改写为复算值+复算注记；要素未齐输出悬置块
        # （含锁定条件）；自洽不动。第9轮末修订（P1-48）：溯源锚点从
        # authoring journey 的 picos.sample_size_anchor 透传上纸。
        anchor = str(
            (
                (expected.get("authoring_journey") or {}).get("picos") or {}
            ).get("sample_size_anchor")
            or ""
        )
        # E11（新纪元第1轮修订）：多重性终点族按 PICOS 结构化终点清单
        # 校验（R1-B 反例：3.2 次要终点全空而统计章声明控制对象）。
        picos_payload = (expected.get("authoring_journey") or {}).get("picos") or {}
        has_key_secondary = bool(picos_payload.get("key_secondary_endpoints"))
        has_other_secondary = bool(picos_payload.get("other_secondary_endpoints"))
        endpoint_families = {
            "主要终点": bool(str(picos_payload.get("primary_endpoint") or "").strip()),
            "关键次要终点": has_key_secondary,
            "次要终点": has_key_secondary or has_other_secondary,
            "探索性终点": bool(picos_payload.get("exploratory_endpoints")),
        }
        # 第3轮·守卫完整性：统一入口（与所有采纳路径共享同一守卫集）。
        apply_full_draft_content_guards(
            all_sections, anchor=anchor, endpoint_families=endpoint_families
        )
        required_review_ids = [
            str(item.get("section_id") or "")
            for item in all_sections
            if item.get("review_level") == "required"
        ]
        decision_required_ids = [
            str(item.get("section_id") or "")
            for item in all_sections
            if item.get("content_status") == "decision_required"
        ]
        source_gap_ids = [
            str(item.get("section_id") or "")
            for item in all_sections
            if item.get("content_status") == "source_gap"
        ]
        partial_ids = [
            str(item.get("section_id") or "")
            for item in all_sections
            if item.get("content_status") == "partial"
        ]
        artifact = {
            "schema_version": FULL_DRAFT_ARTIFACT_SCHEMA,
            "job_id": job.job_id,
            "project_id": job.project_id,
            "document_id": expected["document_id"],
            "document_version": expected["document_version"],
            "precondition_digest": expected["digest"],
            "source_manifest_sha256": expected.get("source_manifest_sha256", ""),
            "source_manifest": self._source_manifest_summary(
                expected.get("source_manifest") or {}
            ),
            "study_definition": expected["study_definition"],
            "authoring_journey": expected.get("authoring_journey") or {},
            "decision_path_owners": decision_path_owners,
            "target_sections": target,
            "sections": all_sections,
            "skipped_chunks": skipped_chunks,
            "coverage": {
                "target_count": len(expected_ids),
                "generated_count": len(all_sections),
                "skipped_count": len(skipped_section_ids),
                "skipped_section_ids": sorted(skipped_section_ids),
                "required_review_count": len(required_review_ids),
                "required_review_section_ids": required_review_ids,
                "decision_required_count": len(decision_required_ids),
                "decision_required_section_ids": decision_required_ids,
                "source_gap_count": len(source_gap_ids),
                "source_gap_section_ids": source_gap_ids,
                "partial_count": len(partial_ids),
                "partial_section_ids": partial_ids,
                "working_draft_ready": any(
                    _text(item.get("proposal_text")) for item in all_sections
                ),
                "formal_ready": not decision_required_ids and not source_gap_ids and not partial_ids,
                "adoption_ready": not decision_required_ids and not source_gap_ids and not partial_ids,
                "section_ids": expected_ids,
            },
            "ai_run_ids": run_ids,
            "ai_route_receipts": route_receipts,
            "source_bindings": source_bindings,
            "created_by": payload.get("actor") or "medical_manager",
        }
        try:
            destination = final_path
            relative = destination.relative_to(self.artifact_root)
            artifact_sha = self._write_json_atomic(destination, artifact)
        except Exception as exc:
            return DurableJobResult(error=f"全文初稿候选持久化失败：{exc}", retryable=False)
        locator = _canonical(
            {
                "schema_version": FULL_DRAFT_ARTIFACT_SCHEMA,
                "artifact_relpath": relative.as_posix(),
                "artifact_sha256": artifact_sha,
                "precondition_digest": expected["digest"],
                "coverage": {
                    key: value
                    for key, value in artifact["coverage"].items()
                    if key not in {
                        "section_ids",
                        "required_review_section_ids",
                        "decision_required_section_ids",
                        "source_gap_section_ids",
                        "partial_section_ids",
                    }
                },
            }
        )
        provider, model = self._result_route_identity(
            route_receipts,
            expected.get("ai_policy") or {},
        )
        return DurableJobResult(
            output_hash=artifact_sha,
            artifact_locator=locator,
            provider=provider,
            model=model,
            progress=DurableJobProgressPayload(
                phase="persisted_candidate",
                percent=1.0,
                step=total,
                step_total=total,
                message=(
                    f"全文初稿已生成 {len(all_sections)}/{len(expected_ids)} 个章节候选，"
                    + (
                        f"另有 {len(skipped_section_ids)} 个章节因服务繁忙或校验失败已跳过（可单独续跑补齐），"
                        if skipped_section_ids
                        else ""
                    )
                    + f"其中 {len(required_review_ids)} 个高影响章节需逐卡确认"
                ),
            ),
        )

    @staticmethod
    def decision_item_id(section_id: str, question: Any) -> str:
        """Deterministic identity of one full-draft decision item.

        The identity is derived from the artifact itself so a decision can be
        resolved and replayed without introducing a second decision store.
        """
        return "fdd_" + _digest(
            {"section_id": _text(section_id), "question": _text(question)}
        )[:24]

    @classmethod
    def decision_index(cls, artifact: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for section in artifact.get("sections") or []:
            if not isinstance(section, Mapping):
                continue
            section_id = _text(section.get("section_id"))
            for item in section.get("decision_items") or []:
                if not isinstance(item, Mapping):
                    continue
                index[cls.decision_item_id(section_id, item.get("question"))] = {
                    "section_id": section_id,
                    "content_status": _text(section.get("content_status")),
                    "item": dict(item),
                }
        return index

    def read_artifact(self, project_id: str, job: Any) -> dict[str, Any]:
        artifact, _ = self.read_frozen_artifact(project_id, job)
        return self._with_decision_identity(self._apply_review_policy(artifact))

    def read_frozen_artifact(
        self, project_id: str, job: Any
    ) -> tuple[dict[str, Any], str]:
        """Read the exact persisted candidate and its verified byte identity.

        Normal reads project decision identities and review policy into an
        in-memory copy.  Candidate acceptance must instead bind its receipt to
        the immutable bytes written by the durable job, so a later read-time
        projection can never change the accepted candidate identity.
        """
        if job.project_id != project_id or job.job_type != FULL_DRAFT_JOB_TYPE:
            raise RuntimeStoreError("全文初稿任务不属于当前项目")
        if job.status != "completed":
            raise RuntimeStoreError(f"全文初稿任务尚未完成：{job.status}")
        locator = json.loads(job.artifact_locator or "{}")
        relative = Path(str(locator.get("artifact_relpath") or ""))
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise RuntimeStoreError("全文初稿候选定位无效")
        path = (self.artifact_root / relative).resolve()
        if self.artifact_root not in path.parents:
            raise RuntimeStoreError("全文初稿候选越界")
        raw = path.read_bytes()
        artifact_sha256 = hashlib.sha256(raw).hexdigest()
        if artifact_sha256 != str(locator.get("artifact_sha256") or ""):
            raise RuntimeStoreError("全文初稿候选完整性校验失败")
        if job.output_hash and artifact_sha256 != str(job.output_hash):
            raise RuntimeStoreError("全文初稿任务与候选身份不一致")
        artifact = json.loads(raw.decode("utf-8"))
        if artifact.get("schema_version") not in {
            FULL_DRAFT_ARTIFACT_SCHEMA,
            *LEGACY_FULL_DRAFT_ARTIFACT_SCHEMAS,
        }:
            raise RuntimeStoreError("全文初稿候选版本不受支持")
        return artifact, artifact_sha256

    @classmethod
    def _with_decision_identity(cls, artifact: dict[str, Any]) -> dict[str, Any]:
        """Project the stable decision identity into a read-time copy.

        The persisted artifact stays byte-identical; clients address a decision
        by the identity derived from the artifact itself instead of inventing
        their own index into a list that may be reordered.
        """
        for section in artifact.get("sections") or []:
            if not isinstance(section, dict):
                continue
            section_id = _text(section.get("section_id"))
            items = section.get("decision_items")
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    item.setdefault(
                        "decision_id",
                        cls.decision_item_id(section_id, item.get("question")),
                    )
        return artifact

    def adopt(
        self,
        project_id: str,
        job: Any,
        *,
        actor: str = "medical_manager",
        confirmed_section_ids: Iterable[str] = (),
        duplicate_dispositions: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        artifact = self.read_artifact(project_id, job)
        if artifact.get("schema_version") != FULL_DRAFT_ARTIFACT_SCHEMA:
            raise RuntimeStoreError("旧版全文初稿候选仅供查阅；请按当前研究事实重新生成后再采纳")
        if not self._artifact_evidence_is_resolvable(artifact):
            raise RuntimeStoreError("全文初稿章节证据链不完整，未采纳")
        service = self._service(project_id)
        repo = service.repo
        document = repo.protocol(project_id)
        if str(document.document_id) != str(artifact.get("document_id")):
            raise RuntimeStoreError("全文初稿所属文档已变化，未采纳")
        if str(document.version) != str(artifact.get("document_version")):
            raise RuntimeStoreError("全文初稿所属文档版本已变化，未采纳")
        if self._binding(repo, project_id, document) != artifact.get("study_definition"):
            raise RuntimeStoreError("研究设计绑定已变化，未采纳全文初稿")
        candidates = {str(item.get("section_id")): item for item in artifact.get("sections") or []}
        target_by_id = {str(item.get("section_id")): item for item in artifact.get("target_sections") or []}
        if set(candidates) != set(target_by_id):
            raise RuntimeStoreError("全文初稿候选覆盖与目标章节不一致")
        # 0924V1-R08: adoption creates an EDITABLE WORKING DRAFT, not the
        # formal deliverable. Non-critical gaps no longer hard-block:
        # - partial sections (substantive proposal text) are written as-is;
        # - source-gap sections are SKIPPED, keeping their existing 待补齐
        #   placeholder blocks so the missing-evidence semantics stay visible;
        # - required-review sections must still be explicitly confirmed
        #   (checked below) — that gate is unchanged.
        gap_section_ids: list[str] = []
        partial_section_ids: list[str] = []
        for section_id, candidate in candidates.items():
            status = str(candidate.get("content_status", "complete"))
            if status == "partial":
                partial_section_ids.append(section_id)
            elif status != "complete":
                gap_section_ids.append(section_id)
        gap_section_id_set = set(gap_section_ids)
        # P0-A（NEW-13 根治）：采纳前对 target_sections 全集做跨节重复扫描
        # （缺口节本就不写入，不参与）；重复即拒绝采纳并点名节号——把生成
        # 层漏网的跨批重复挡在落盘之前。
        duplicates = find_full_draft_duplicate_sections(
            [
                {"section_id": section_id, "proposal_text": candidate.get("proposal_text")}
                for section_id, candidate in candidates.items()
                if section_id not in gap_section_id_set
            ]
        )
        # 复测N1（第3轮）：重复门从一票否决改为逐节处置——'skip'=本节跳过
        # 采纳（维持占位）、'adopt_with_gap'=仍要采纳（计入装配重复缺口，
        # 导出层草案-N）；'重生成'走既有取消+重提交通道。未提供处置表时
        # 维持 fail-safe 整体拒绝（API 旧调用方语义不变），异常携带结构化
        # 重复对供采纳面板列出三选一。
        skipped_duplicate_sections: list[str] = []
        assembly_duplicate_sections: list[str] = []
        if duplicates:
            dup_section_ids = {
                sid for ids in duplicates.values() for sid in ids
            }
            dispositions = dict(duplicate_dispositions or {})
            invalid = sorted(
                sid for sid, action in dispositions.items()
                if action not in {"skip", "adopt_with_gap"}
            )
            if invalid:
                raise ValueError(
                    "重复处置值非法（仅允许 skip/adopt_with_gap）："
                    + "、".join(invalid)
                )
            resolved_group = False
            for signature, members in duplicates.items():
                actions = {
                    sid: dispositions.get(sid)
                    for sid in members
                    if dispositions.get(sid)
                }
                skips = [sid for sid, a in actions.items() if a == "skip"]
                keeps = [sid for sid, a in actions.items() if a == "adopt_with_gap"]
                undecided = [sid for sid in members if sid not in actions]
                remaining = len(members) - len(skips)
                if remaining <= 1:
                    # 跳过后组内至多剩一节：共享片段已唯一化——跳过节维持
                    # 占位，余节自动消解为普通采纳（无需处置）。
                    resolved_group = True
                    for sid in skips:
                        if sid not in skipped_duplicate_sections:
                            skipped_duplicate_sections.append(sid)
                            gap_section_id_set.add(sid)
                            gap_section_ids.append(sid)
                elif keeps and not undecided:
                    # 全组逐节表态'仍要采纳'：逐节计入装配重复缺口
                    #（导出层草案-N）；三选一是逐节契约，未表态即拒绝。
                    resolved_group = True
                    for sid in keeps:
                        if sid not in assembly_duplicate_sections:
                            assembly_duplicate_sections.append(sid)
                elif undecided:
                    # 组内仍有多节共存且有未处置节——等处置齐全再定。
                    continue
            if not resolved_group:
                undecided = sorted(dup_section_ids - set(dispositions))
                named = "、".join(
                    str(candidates.get(sid, {}).get("section_number") or sid)
                    for sid in undecided
                )
                message = (
                    "全文初稿候选存在跨节重复正文（章节内容装配重复），本次未采纳；"
                    "请对涉事节逐节选择跳过/重生成/仍要采纳。"
                    + _duplicate_section_names(duplicates)
                )
                if undecided:
                    message += f"——仍有未处置章节：{named}"
                raise FullDraftDuplicateSectionsError(
                    message,
                    duplicate_pairs=_duplicate_pairs_payload(
                        duplicates, candidates
                    ),
                    undecided_section_ids=undecided,
                )
            skipped_duplicate_sections = list(dict.fromkeys(skipped_duplicate_sections))
            assembly_duplicate_sections = list(dict.fromkeys(assembly_duplicate_sections))
        required_review_ids = {
            section_id
            for section_id, candidate in candidates.items()
            if candidate.get("review_level") == "required"
        }
        missing_confirmations = sorted(
            required_review_ids.difference(
                str(item) for item in confirmed_section_ids if str(item).strip()
            )
        )
        if missing_confirmations:
            raise RuntimeStoreError(
                f"仍有 {len(missing_confirmations)} 个高影响章节未逐卡确认，全文初稿未写入"
            )
        adopted: list[str] = []
        replayed: list[str] = []
        for section_id, target in target_by_id.items():
            if section_id in gap_section_id_set:
                # Source-gap section: leave the existing 待补齐 placeholder
                # blocks untouched — the missing-evidence semantics must stay
                # visible in the working draft instead of being written over.
                continue
            candidate = candidates[section_id]
            proposal = _text(candidate.get("proposal_text"))
            if (
                len(proposal) < FULL_DRAFT_MINIMUM_BODY_CHARS
                or _PLACEHOLDER_RE.search(proposal)
                or INTERNAL_TRANSPORT_VOCABULARY_RE.search(proposal)
                or DRAFTING_PROCESS_VOCABULARY_RE.search(proposal)
                or next(iter_unresolved_draft_markers(proposal), None)
            ):
                raise RuntimeStoreError(f"全文初稿章节候选不具备实质内容：{section_id}")
            current = repo.working_copy(project_id, section_id)
            blocks = [dict(block) for block in current.content_blocks]
            body_index = next(
                (index for index, block in enumerate(blocks) if str(block.get("block_id")) == str(target.get("body_block_id"))),
                None,
            )
            if body_index is None:
                raise RuntimeStoreError(f"全文初稿目标正文块不存在：{section_id}")
            current_text = _text(blocks[body_index].get("text"))
            if current_text == proposal:
                replayed.append(section_id)
                continue
            if current.revision != int(target.get("expected_revision") or 0):
                raise StaleRuntimeStateError(f"全文初稿采纳遇到章节版本变化：{section_id}")
            if hashlib.sha256(current_text.encode("utf-8")).hexdigest() != str(target.get("body_sha256") or ""):
                raise StaleRuntimeStateError(f"全文初稿采纳遇到正文变化：{section_id}")
            blocks[body_index]["text"] = proposal
            expected_next_revision = current.revision + 1
            saved = repo.save_working_copy(
                project_id,
                section_id,
                MedicalWritingWorkingCopySaveRequest(
                    document_id=document.document_id,
                    expected_revision=current.revision,
                    content_blocks=blocks,
                    actor=actor,
                    idempotency_key=f"full-draft-adopt:{job.job_id}:{section_id}",
                ),
            )
            if saved.revision != expected_next_revision:
                raise RuntimeStoreError(f"全文初稿采纳未形成预期章节版本：{section_id}")
            adopted.append(section_id)
        return {
            "job_id": job.job_id,
            "project_id": project_id,
            "artifact_schema": FULL_DRAFT_ARTIFACT_SCHEMA,
            "adopted_section_ids": adopted,
            "replayed_section_ids": replayed,
            "adopted_count": len(adopted),
            "replayed_count": len(replayed),
            "skipped_duplicate_sections": skipped_duplicate_sections,
            "assembly_duplicate_sections": assembly_duplicate_sections,
            # 0924V1-R08: gap sections stay as visible 待补齐 placeholders in
            # the working draft; partial sections were written as-is.
            "gap_section_ids": sorted(gap_section_id_set),
            "gap_count": len(gap_section_id_set),
            "partial_section_ids": sorted(partial_section_ids),
            "partial_written_count": len(partial_section_ids),
            "coverage": artifact.get("coverage") or {},
        }

    @staticmethod
    def _decision_fact_value(fact_path: str, value: str) -> Any:
        """Shape one confirmed prose answer for its authoritative field.

        A decision card's answer is a single confirmed statement.  Scalar
        fields take it as-is; fields the StudyDefinition models declare as
        string lists receive a single-item list, the shape the existing
        adoption validation accepts for that declared field type.
        """
        root, _, rest = fact_path.partition(".")
        model = {
            "framing": MedicalWritingStudyFraming,
            "picos": MedicalWritingPicosDefinition,
        }.get(root)
        if model is None:
            return value
        cursor = model
        parts = [part for part in rest.split(".") if part]
        for index, part in enumerate(parts):
            field = cursor.model_fields.get(part)
            if field is None:
                return value
            annotation = field.annotation
            if index == len(parts) - 1:
                if get_origin(annotation) is list and get_args(annotation) == (str,):
                    return [value]
                return value
            if not hasattr(annotation, "model_fields"):
                return value
            cursor = annotation
        return value

    def resolve_decision(
        self,
        project_id: str,
        durable_store: DurableJobStore,
        job: Any,
        *,
        decisions: Iterable[Mapping[str, Any]],
        idempotency_key: str,
        actor: str = "medical_manager",
        study_definition_writer: Optional[Callable[..., Any]] = None,
    ) -> dict[str, Any]:
        """Resolve full-draft decision cards in one explicit confirmation.

        The answer is written by the existing authoritative StudyDefinition
        confirmation channel handed in as ``study_definition_writer``; this
        service never invents a fact path and never keeps a decision store of
        its own.  A decision item that does not carry an already supported
        authoritative fact path fails closed.

        Resolution order matters and is preserved:

        1. validate every decision against the current immutable artifact;
        2. persist the confirmed answers through the existing channel (CAS plus
           audit live inside that channel);
        3. the persisted StudyDefinition revision invalidates this artifact
           under the existing ``adopt`` binding check — the artifact is never
           rewritten;
        4. submit a new full-draft job scoped to the affected sections only.
        """
        artifact = self.read_artifact(project_id, job)
        if artifact.get("schema_version") != FULL_DRAFT_ARTIFACT_SCHEMA:
            raise RuntimeStoreError(
                "旧版全文初稿候选仅供查阅；请按当前研究事实重新生成后再确认决定"
            )
        service = self._service(project_id)
        repo = service.repo
        document = repo.protocol(project_id)
        if str(document.document_id) != str(artifact.get("document_id")) or str(
            document.version
        ) != str(artifact.get("document_version")):
            raise StaleRuntimeStateError("全文初稿所属文档已变化，决定未写入")
        key = _text(idempotency_key)
        if not key:
            raise ValueError("全文初稿决定确认需要 idempotency_key")
        index = self.decision_index(artifact)
        writer = study_definition_writer
        if writer is None or not callable(writer):
            raise RuntimeStoreError(
                "全文初稿决定尚未绑定研究设计确认通道，未写入任何研究事实"
            )
        submitted = list(decisions)
        if not 1 <= len(submitted) <= 6:
            raise ValueError("一次可确认1至6个相互关联的全文初稿决定")
        resolved: list[dict[str, Any]] = []
        seen: set[str] = set()
        seen_fact_paths: set[str] = set()
        for raw in submitted:
            if not isinstance(raw, Mapping):
                raise ValueError("全文初稿决定必须是对象")
            decision_id = _text(raw.get("decision_id"))
            option_id = _text(raw.get("option_id"))
            if not decision_id or not option_id:
                raise ValueError("全文初稿决定需要 decision_id 与 option_id")
            if decision_id in seen:
                raise ValueError(f"全文初稿决定重复提交：{decision_id}")
            seen.add(decision_id)
            entry = index.get(decision_id)
            if entry is None:
                raise RuntimeStoreError(f"全文初稿候选不存在该决定项：{decision_id}")
            if entry["content_status"] not in {"decision_required", "partial"}:
                raise RuntimeStoreError(
                    f"该章节当前不是待决定状态，不能按决定项确认：{entry['section_id']}"
                )
            item = entry["item"]
            option = next(
                (
                    candidate
                    for candidate in item.get("options") or []
                    if _text(candidate.get("option_id")) == option_id
                ),
                None,
            )
            if option is None:
                raise RuntimeStoreError(
                    f"全文初稿决定项没有该选项：{decision_id}/{option_id}"
                )
            fact_path = _text(item.get("fact_path"))
            if not fact_path:
                raise RuntimeStoreError(
                    "决定项未绑定研究设计字段路径，无法写入权威研究设计；"
                    "请先在既有研究设计流程中确认该决定"
                )
            if fact_path not in SUPPORTED_ADOPT_PATHS:
                raise RuntimeStoreError(
                    f"决定项目标不是既有研究设计字段：{fact_path}"
                )
            if fact_path in seen_fact_paths:
                raise ValueError(f"同一研究字段不能在一组决定中重复确认：{fact_path}")
            seen_fact_paths.add(fact_path)
            if fact_path in _DECISION_STRUCTURED_DESIGN_PATHS:
                raise RuntimeStoreError(
                    f"决定项目标路径需要结构化设计取值，决定卡无法安全写入：{fact_path}；"
                    "请在研究设计中直接确认该决定"
                )
            if (artifact.get("decision_path_owners") or {}).get(fact_path) != entry["section_id"]:
                raise RuntimeStoreError(
                    f"决定项不属于该研究字段的指定章节：{fact_path}"
                )
            prose = _text(option.get("summary")) or _text(option.get("label"))
            resolved.append(
                {
                    "decision_id": decision_id,
                    "section_id": entry["section_id"],
                    "question": _text(item.get("question")),
                    "option_id": option_id,
                    "recommended_option_id": _text(item.get("recommended_option_id")),
                    "fact_path": fact_path,
                    "value": self._decision_fact_value(fact_path, prose),
                }
            )
        if not resolved:
            raise ValueError("全文初稿决定确认为空")

        for entry in resolved:
            value = entry["value"]
            if not value:
                raise RuntimeStoreError(
                    f"决定项选项缺少可写入的实质内容：{entry['decision_id']}"
                )
        journey_binding = artifact.get("authoring_journey") or {}
        expected_journey_revision = journey_binding.get("journey_revision")
        if not isinstance(expected_journey_revision, int):
            raise RuntimeStoreError("全文初稿缺少可恢复的研究确认版本，决定未写入")
        outcome = writer(
            project_id,
            decisions=resolved,
            expected_journey_revision=expected_journey_revision,
            authoring_journey_binding=journey_binding,
            actor=actor,
            idempotency_key=(
                f"full-draft-decision-group:{job.job_id}:{_digest(key)[:24]}"
            ),
        )
        confirmations = [{
            "decision_id": entry["decision_id"],
            "section_id": entry["section_id"],
            "fact_path": entry["fact_path"],
            "option_id": entry["option_id"],
            "study_definition_revision": getattr(
                getattr(outcome, "study_definition", None), "revision", None
            ),
            "journey_revision": getattr(outcome, "revision", None),
        } for entry in resolved]

        affected_section_ids = sorted(
            {entry["section_id"] for entry in resolved}
        )
        regenerated_job_id, reused = self.submit_durable(
            project_id,
            durable_store,
            actor=actor,
            section_ids=affected_section_ids,
        )
        return {
            "job_id": job.job_id,
            "project_id": project_id,
            "artifact_schema": FULL_DRAFT_ARTIFACT_SCHEMA,
            # The written StudyDefinition revision makes this artifact stale for
            # every existing consumer: ``adopt`` already refuses it through the
            # unchanged binding check, and the scoped descriptor guarantees a
            # different durable job.  No artifact byte is rewritten.
            "superseded_job_id": job.job_id,
            "resolved_decisions": resolved,
            "study_definition_confirmations": confirmations,
            "affected_section_ids": affected_section_ids,
            "regeneration": {
                "job_id": regenerated_job_id,
                "reused": bool(reused),
                "section_ids": affected_section_ids,
            },
        }


class ProtocolFullDraftExecutor(DurableJobExecutor):
    job_type = FULL_DRAFT_JOB_TYPE

    def __init__(self, service: MedicalWritingFullDraftService) -> None:
        self.service = service

    def execute(
        self,
        job: Any,
        claim_token: str,
        cancel_check: Callable[[], bool],
        heartbeat: Callable[[DurableJobProgressPayload], bool],
    ) -> DurableJobResult:
        return self.service.run_job(job, claim_token, cancel_check, heartbeat)
