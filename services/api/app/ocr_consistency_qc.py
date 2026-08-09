"""Focused translation-support-LLM consistency QC for mixed-model OCR evidence.

When one document contains OCR evidence from more than one model (e.g.,
Paddle for some pages and GLM for others), this module runs exactly one
focused consistency check via the translation-support LLM before the
evidence is admitted to the competitor corpus.

The QC model must NOT rewrite OCR text.  It only returns a bounded audit
outcome (pass/fail + notes).  All LLM interaction is injectable for
deterministic tests.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any, Callable, Sequence, Union

QC_STAGE_VERSION = "mixed_ocr_consistency_qc_v2_1"
QC_SCHEMA_VERSION = "mixed_ocr_consistency_qc_v2"
# A mixed-OCR document can contain dozens of fallback pages.  Sending every
# page to the reasoning model makes the otherwise bounded QC call effectively
# unbounded (and can leave a preparation worker waiting on a large upstream
# response).  Keep the evidence window deterministic and fail closed when it
# is reduced; the source OCR remains untouched and the medical reviewer still
# sees the full page-level audit trail in the persisted extraction.
QC_MAX_BOUNDARY_PAGES = 8
QC_MAX_PROMPT_CHARS = 48_000
QC_PAGE_TEXT_LIMIT = 6_000

# Callable signature: (system_prompt, user_prompt) -> {"verdict": str, "notes": str}
ConsistencyQcRunner = Callable[[str, str], dict[str, Any]]
PageEvidence = Union[
    tuple[str, str],
    tuple[int, str, str],
    Mapping[str, Any],
]
NormalizedPageEvidence = dict[str, Any]


class MixedOcrConsistencyQcError(RuntimeError):
    """Raised when the consistency QC stage fails or returns invalid output."""


@dataclass(frozen=True)
class MixedOcrConsistencyQcOutcome:
    """Bounded audit outcome for a mixed-model OCR consistency check."""

    triggered: bool
    verdict: str  # "pass" | "review_required" | "fail"
    models: tuple[str, ...]
    page_count: int
    qc_stage_version: str = QC_STAGE_VERSION
    qc_schema_version: str = QC_SCHEMA_VERSION
    notes: str = ""
    identity_hash: str = ""

    def audit_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "triggered": self.triggered,
            "verdict": self.verdict,
            "models": list(self.models),
            "page_count": self.page_count,
            "qc_stage_version": self.qc_stage_version,
            "qc_schema_version": self.qc_schema_version,
            "notes": self.notes,
            "identity_hash": self.identity_hash,
        }
        return payload


_SYSTEM_PROMPT = (
    "你是临床试验方案 OCR 一致性审查助手。你将收到同一份文档中实际发生OCR模型回退"
    "或切换的物理页，以及同页原生提取文本和真实相邻物理页上下文（如有）。"
    "同页原生文本可能因复杂表格而不完整，只能作为交叉线索；不得要求逐字相同。"
    "不同物理页也不得因文字本来不同而判为不一致。只检查回退页本身是否存在可疑的"
    "章节或句子断裂、标题和条款编号跳变、表格行列错位，以及数值、单位、比较符号、"
    "否定词或给药信息的异常遗漏或改变。研究流程表/访视计划表中的大量重复X通常是"
    "各访视按计划执行该项目的正常标记，不能仅因X重复或原生文本没有完整提取X而判为异常。"
    "输入块如标注“显示已截断”则不得把块末尾不完整当成OCR缺失。"
    "证据不足时返回 review_required，并在 notes 中指出需要核对的具体边界，不得臆测原文。"
    "你绝对不得改写、修正或重写任何 OCR 文本。"
    "只返回 JSON：{\"verdict\": \"pass|review_required|fail\", \"notes\": \"简要说明\"}。"
)


def _normalize_page_evidence(
    page_texts: Sequence[PageEvidence],
) -> list[NormalizedPageEvidence]:
    normalized: list[NormalizedPageEvidence] = []
    for fallback_page_number, item in enumerate(page_texts, start=1):
        if isinstance(item, Mapping):
            page_number = item.get("physical_page", fallback_page_number)
            model = item.get("model", "")
            text = item.get("text", "")
            normalized.append(
                {
                    "physical_page": int(page_number),
                    "model": str(model),
                    "text": str(text),
                    "fell_back": bool(item.get("fell_back", False)),
                    "native_text": str(item.get("native_text", "")),
                    "previous_page_text": str(item.get("previous_page_text", "")),
                    "next_page_text": str(item.get("next_page_text", "")),
                }
            )
            continue
        if len(item) == 3:
            page_number, model, text = item
        else:
            model, text = item
            page_number = fallback_page_number
        normalized.append(
            {
                "physical_page": int(page_number),
                "model": str(model),
                "text": str(text),
                "fell_back": False,
                "native_text": "",
                "previous_page_text": "",
                "next_page_text": "",
            }
        )
    return normalized


def _model_boundary_window(
    page_texts: Sequence[NormalizedPageEvidence],
) -> list[NormalizedPageEvidence]:
    fallback_pages = [item for item in page_texts if item["fell_back"]]
    if fallback_pages:
        return fallback_pages
    selected: set[int] = set()
    for index in range(1, len(page_texts)):
        previous = page_texts[index - 1]
        current = page_texts[index]
        if previous["model"].strip() == current["model"].strip():
            continue
        if current["physical_page"] - previous["physical_page"] != 1:
            continue
        selected.update((index - 1, index))
    return [item for index, item in enumerate(page_texts) if index in selected]


def _build_user_prompt(page_texts: Sequence[NormalizedPageEvidence]) -> str:
    """Build a prompt containing only real OCR-model transition windows."""
    bounded = list(page_texts)
    reduced = False
    if len(bounded) > QC_MAX_BOUNDARY_PAGES:
        # Preserve both ends of the transition window instead of silently
        # favouring the first pages; any omitted pages are explicitly marked
        # so the model cannot treat the sample as complete evidence.
        head = QC_MAX_BOUNDARY_PAGES // 2
        tail = QC_MAX_BOUNDARY_PAGES - head
        bounded = bounded[:head] + bounded[-tail:]
        reduced = True
    lines = [
        "以下仅列出同一文档中实际发生模型回退/切换的物理页。",
        "如提供同页原生文本或相邻物理页，只用于定位明显OCR异常；不要把正常分页、"
        "原生提取不完整、目录页码或不同章节内容判为模型不一致：",
        "",
    ]
    if reduced:
        lines.extend(
            [
                "注意：实际回退页超过本次 QC 的确定性输入上限，以下为首尾边界抽样；"
                "显示已截断，不得据此判定未列出的页没有异常。证据不足时必须返回 review_required。",
                "",
            ]
        )
    for item in bounded:
        page_number = item["physical_page"]
        model = item["model"]
        text = item["text"]
        text_limit = QC_PAGE_TEXT_LIMIT
        preview = text[:text_limit] if len(text) > text_limit else text
        lines.append(
            f"--- 物理页 {page_number} (模型: {model}; "
            f"{'主模型失败后回退' if item['fell_back'] else '模型切换边界'}) ---"
        )
        if item["previous_page_text"]:
            lines.append("[前一物理页上下文]")
            previous = item["previous_page_text"]
            lines.append(previous[:3000])
            if len(previous) > 3000:
                lines.append("[前一物理页上下文显示已截断]")
        if item["native_text"]:
            lines.append("[同页原生提取文本，仅作交叉线索]")
            native = item["native_text"]
            lines.append(native[:6000])
            if len(native) > 6000:
                lines.append("[同页原生提取文本显示已截断]")
        lines.append("[本页OCR文本]")
        lines.append(preview)
        if len(text) > text_limit:
            lines.append("[本页OCR文本显示已截断]")
        if item["next_page_text"]:
            lines.append("[后一物理页上下文]")
            following = item["next_page_text"]
            lines.append(following[:3000])
            if len(following) > 3000:
                lines.append("[后一物理页上下文显示已截断]")
        lines.append("")
    lines.append("请仅判断上述回退/切换页是否存在具体、可定位的可疑OCR异常，返回 JSON。")
    prompt = "\n".join(lines)
    if len(prompt) > QC_MAX_PROMPT_CHARS:
        prompt = prompt[:QC_MAX_PROMPT_CHARS]
        prompt += (
            "\n\n[整体 QC 输入达到确定性字符上限，显示已截断；"
            "不得把未显示部分视为无异常，证据不足时返回 review_required。]"
        )
    return prompt


def _compute_identity_hash(
    models: tuple[str, ...],
    page_texts: Sequence[NormalizedPageEvidence],
) -> str:
    payload = {
        "models": list(models),
        "pages": [
            {
                "physical_page": item["physical_page"],
                "model": item["model"],
                "fell_back": item["fell_back"],
                "text_sha256": hashlib.sha256(
                    item["text"].encode("utf-8")
                ).hexdigest(),
                "native_text_sha256": hashlib.sha256(
                    item["native_text"].encode("utf-8")
                ).hexdigest(),
                "previous_page_text_sha256": hashlib.sha256(
                    item["previous_page_text"].encode("utf-8")
                ).hexdigest(),
                "next_page_text_sha256": hashlib.sha256(
                    item["next_page_text"].encode("utf-8")
                ).hexdigest(),
            }
            for item in page_texts
        ],
        "stage_version": QC_STAGE_VERSION,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_mixed_ocr_consistency_qc(
    page_evidence: Sequence[PageEvidence],
    qc_runner: ConsistencyQcRunner,
) -> MixedOcrConsistencyQcOutcome:
    """Run the focused consistency QC for mixed-model OCR evidence.

    ``page_evidence`` is a sequence of (model, text) tuples — one per page
    that has OCR evidence in this document.

    If the evidence uses only one model (or is empty), the QC is NOT
    triggered and returns ``triggered=False``.

    The QC runs exactly once.  The runner must not rewrite OCR text; it
    only returns a verdict.
    """
    if not page_evidence:
        return MixedOcrConsistencyQcOutcome(
            triggered=False,
            verdict="pass",
            models=(),
            page_count=0,
            notes="no OCR evidence; QC not triggered",
        )

    normalized_evidence = _normalize_page_evidence(page_evidence)
    models_set = {
        item["model"].strip()
        for item in normalized_evidence
        if item["model"] and item["model"].strip()
    }
    if len(models_set) <= 1:
        return MixedOcrConsistencyQcOutcome(
            triggered=False,
            verdict="pass",
            models=tuple(sorted(models_set)),
            page_count=len(page_evidence),
            notes="single-model evidence; QC not triggered",
        )

    # Mixed model — run QC exactly once.
    models_tuple = tuple(sorted(models_set))
    boundary_evidence = _model_boundary_window(normalized_evidence)
    if not boundary_evidence:
        return MixedOcrConsistencyQcOutcome(
            triggered=False,
            verdict="pass",
            models=models_tuple,
            page_count=len(page_evidence),
            notes=(
                "mixed OCR models occurred only on nonadjacent selected pages; "
                "no real model-switch boundary required consistency QC"
            ),
            identity_hash=_compute_identity_hash(models_tuple, normalized_evidence),
        )
    user_prompt = _build_user_prompt(boundary_evidence)
    identity_hash = _compute_identity_hash(models_tuple, normalized_evidence)

    try:
        raw_result = qc_runner(_SYSTEM_PROMPT, user_prompt)
    except Exception as exc:
        raise MixedOcrConsistencyQcError(
            f"consistency QC runner failed: {_sanitize(str(exc))}"
        ) from exc

    verdict = str(raw_result.get("verdict", "")).strip().casefold()
    if verdict not in {"pass", "review_required", "fail"}:
        raise MixedOcrConsistencyQcError(
            f"consistency QC returned invalid verdict: {verdict!r}"
        )
    notes = str(raw_result.get("notes", "")).strip()

    return MixedOcrConsistencyQcOutcome(
        triggered=True,
        verdict=verdict,
        models=models_tuple,
        page_count=len(page_evidence),
        notes=notes,
        identity_hash=identity_hash,
    )


def _sanitize(text: str) -> str:
    import re

    return re.sub(r"[A-Za-z0-9]{32,}", "[redacted]", text[:120])
