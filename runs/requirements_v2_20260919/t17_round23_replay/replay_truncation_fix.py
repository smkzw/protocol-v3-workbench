#!/usr/bin/env python3
"""Round23 truncation-fix diagnostic replay — REAL model, ZERO DB writes.

Regenerates the NCT02176291 sample translation under the FIXED chunker
(the 4865-char single-paragraph span now splits into bounded chunks) and
runs the normal deterministic fidelity gate on the complete candidate.

Faithful to the production path:
- the persisted document plan is replayed (no planning call);
- the body translator replicates main.py `_hy_mt2_translator_adapter`
  verbatim (system prompt, envelope, temperature 0, max_tokens 4096,
  truncated/empty output fails closed, oMLX workload-gate lease);
- bounded correction runs via the production
  `translate_units_with_bounded_correction`;
- the deterministic gate is the production
  `evaluate_translation_fidelity_aligned_units`.

Model lifecycle: the model is loaded/released ONLY through the authorized
orchestrator (`ensure_phase("translation")`).  Nothing is written to any
database: evidence goes to stdout/JSON in this directory only.  Fidelity
findings are EVIDENCE for the human medical gate — nothing is admitted,
no generation_status changes anywhere.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace

REPO = Path(
    "/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/"
    "implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313"
)
ISO = (
    REPO
    / "runs/requirements_v2_20260919/wp6_0922v2_20260922"
    / "real_http_acceptance/isolated_runtime"
)
OUT_DIR = REPO / "runs/requirements_v2_20260919/t17_round23_replay"

os.environ["WORKBENCH_RUNTIME_DIR"] = str(ISO)
os.environ["WORKBENCH_AI_SETTINGS_PATH"] = str(ISO / "ai_provider_settings.json")
sys.path.insert(0, str(REPO / "services" / "api"))
sys.path.insert(0, str(REPO))

PROJECT = "proj_user_fad9f64f3151"
PLAN_ID = "docplan_555b14f4c8150232565e1cb0"
SPAN_ID = "wref_span_9669b181c91ae7a58c824426"
CHAPTER = "ch_232c9ebdb6e023c8f14fc6dceb7829aaaad6190b6e7475f4c5e919714e177210"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- lifecycle
from app.model_lifecycle_orchestrator import ensure_phase, lifecycle_status  # noqa: E402

ENSURE = ensure_phase("translation")
print("[lifecycle] ensure(translation):", json.dumps(ENSURE, ensure_ascii=False)[:400])
STATUS = lifecycle_status()
print("[lifecycle] status:", json.dumps(STATUS, ensure_ascii=False)[:400])

# ------------------------------------------------------------ role binding
from app.ai_role_runtime_settings import (  # noqa: E402
    TRANSLATION_BODY_ROLE,
    runtime_ai_role_settings_store,
)

_store = runtime_ai_role_settings_store()
_store.migrate()
_binding = _store.binding(TRANSLATION_BODY_ROLE)
_profile = _store.provider_store.profile(_binding.profile_id)
_values = _store.role_env(TRANSLATION_BODY_ROLE)
assert _binding.enabled and _profile.enabled, "translation_body binding disabled"
BODY_MODEL = _binding.model
BASE_URL = _values.get("WORKBENCH_AI_BASE_URL", "").strip().rstrip("/")
API_KEY = _values.get("WORKBENCH_AI_API_KEY", "") or "not-required"
USE_OMLX_GATE = _profile.provider.strip().lower() == "omlx"
print(f"[binding] model={BODY_MODEL} base={BASE_URL} omlx_gate={USE_OMLX_GATE}")
assert BASE_URL, "translation_body role has no provider base URL"

# ------------------------------------------------------------- persisted text
import sqlite3  # noqa: E402

DB = ISO / "writing_reference.sqlite3"
_conn = sqlite3.connect(f"file:{DB}?immutable=1", uri=True)
SOURCE_TEXT = json.loads(
    _conn.execute(
        "SELECT payload_json FROM writing_reference_source_spans WHERE span_id=?",
        (SPAN_ID,),
    ).fetchone()[0]
)["source_text"]
PLAN_PAYLOAD = json.loads(
    _conn.execute(
        "SELECT payload_json FROM writing_reference_document_structure_plans"
        " WHERE project_id=? AND plan_id=?",
        (PROJECT, PLAN_ID),
    ).fetchone()[0]
)
_conn.close()

# ------------------------------------------------- deterministic chunking (fixed)
from app.chapter_translation_pipeline import (  # noqa: E402
    DocumentPlanResult,
    HyMt2TranslationResult,
    build_chunks_from_plan,
    evaluate_translation_fidelity_aligned_units,
    format_hy_mt2_prompt_envelope,
    reassemble_aligned_translation,
    split_source_into_units,
    translate_units_with_bounded_correction,
    validate_completion_payload,
    HY_MT2_PROMPT_VERSION,
)
from app.regulatory_translation_glossary import (  # noqa: E402
    render_preferred_abbreviation_contract,
    render_regulatory_translation_glossary_contract,
)
from app.writing_reference import detect_clinical_abbreviations  # noqa: E402
from app.omlx_workload_gate_client import run_gated_omlx_request  # noqa: E402

plan_result = DocumentPlanResult(
    flash_plan=None,  # type: ignore[arg-type]
    chapters=tuple(
        (
            chapter["chapter_id"],
            chapter["title"],
            chapter.get("ich_m11_anchor", ""),
            tuple(chapter["source_span_ids"]),
        )
        for chapter in PLAN_PAYLOAD["chapters"]
    ),
    document_role=PLAN_PAYLOAD["document_role"],
    ambiguity_codes=tuple(PLAN_PAYLOAD.get("ambiguity_codes", ())),
)
span_obj = SimpleNamespace(span_id=SPAN_ID, source_text=SOURCE_TEXT)
chunks = []
for entry in build_chunks_from_plan(plan_result, (span_obj,)):
    for key, chapter_chunks in entry.items():
        if key[0] == CHAPTER:
            chunks = list(chapter_chunks)
print(f"[chunking] source={len(SOURCE_TEXT)} chars -> {len(chunks)} chunks: "
      f"{[len(c.source_text) for c in chunks]}")
assert chunks, "no chunks built"

# ------------------------------------------- real translator (adapter copy)
SYSTEM_PROMPT = (
    "你是临床试验方案翻译引擎。"
    "将 SOURCE_TEXT 英文方案段落翻译为自然、准确的中国监管中文。"
    "READ_ONLY_CONTEXT 仅供衔接参考，禁止翻译或复制到输出。"
    "输出必须且仅对应 SOURCE_TEXT。\n"
    "【对齐翻译单元规则】源文本已用 [[CMS_SEG_NNNN]] ... "
    "[[/CMS_SEG_NNNN]] 标记划分为有序翻译单元。你必须为每个单元输出"
    "对应的同名标记块，每个标记恰好出现一次，序号与顺序严格一致，"
    "不得合并、拆分、遗漏或重排单元。每个标记块内只输出该单元的中文"
    "译文，不得输出任何解释。\n"
    "【忠实度规则】逐单元完整翻译，禁止摘要、压缩、合并或省略任何"
    "项目符号、编号条款、表格行或事实。保持所有数字、引文标记(如(62))、"
    "单位、比较符方向(≥/≤/>/</至少/至多/不低于/不高于)、时间点与"
    "时间窗、否定关系、终点层级(主要/次要/探索性)、动作主体与给药频次"
    "不变。表格单元格内每个“•”项目符号必须在对应单元格原位逐个保留，"
    "不得改成冒号、顿号或直接删除。比较符必须与同一原文单元中紧随其后"
    "的原始数值和单位绑定；"
    "年龄下界的'≥'可表达为'周岁及以上'，但只能使用原文实际下界，"
    "不得从规则、示例或上下文引入原文不存在的年龄或阈值。"
    "'未满'/'不满'须保留排他边界语义；范围连接符(dash)译为'至'，"
    "不得改变上下界。"
    "缩略语定义单元必须严格保持“缩写 = 中文术语”的定义结构，"
    "不得补写用途、适用人群、机制、解释或其他原文没有的定义内容。"
    "每条定义必须直接输出ASCII等号字符“=”，不得用“表示、即、为、是、"
    "则是”等连接词替代；等号左侧ASCII缩写不得翻译。"
    "百分比降低定义只翻译术语并保留原百分比，"
    "不得改写成完全清除、降至零或推定的量表终点评分。"
    "Panel、Table、Figure、Section等标签后的阿拉伯编号在中文中仍须"
    "保留同一个阿拉伯数字，不得改写为中文数字。"
    "参考文献条目必须逐项保留原文的文章编号、年份、月份、日期、卷、期、"
    "完整页码范围、PMID、PMCID、DOI及Epub完整日期；不得缩短页码，"
    "不得把完整日期缩写为年份或年月，也不得省略任何原文已有书目信息。"
    "药物与治疗类别术语必须保持类别层级，不得将类别窄化为单一产品"
    "(例如 TCI 必须译为钙调神经磷酸酶抑制剂类，不得译为他克莫司软膏)。"
    "临床试验方案中的 subjects/participants 必须统一译为“受试者”；"
    "只有原文明确使用 patient/patients 时才可译为“患者”，同一源单元"
    "不得把 subjects 在前后分句中分别译为“受试者”和“患者”。"
)

_CALL_LOG: list[dict] = []


def real_hy_mt2_translator(
    source_text: str,
    glossary: str,
    chapter_id: str,
    chunk_id: str,
    read_only_context: str = "",
    correction_note: str = "",
) -> HyMt2TranslationResult:
    """Faithful copy of main.py `_hy_mt2_translator_adapter`."""
    user_content = format_hy_mt2_prompt_envelope(
        source_text, read_only_context=read_only_context
    )
    if correction_note:
        user_content = f"{user_content}\n\n{correction_note}"
    system_prompt = SYSTEM_PROMPT
    inclusive_age_ranges = re.findall(
        r"(\d+(?:\.\d+)?)\s*(?:to|through|[\u2013\u2014-])\s*"
        r"(\d+(?:\.\d+)?)\s*years?(?:\s+old|\s+of\s+age)?"
        r"[^()\n]{0,40}\((?:both\s+included|inclusive)\)",
        source_text,
        re.IGNORECASE,
    )
    if inclusive_age_ranges:
        rendered_ranges = "；".join(
            f"{lower}至{upper}周岁（含两端值）"
            for lower, upper in inclusive_age_ranges
        )
        system_prompt += (
            "\n【本源文年龄边界】原文明确上下限均包含，必须写为："
            f"{rendered_ranges}。不得使用“{inclusive_age_ranges[0][1]}"
            "周岁以下”“未满”或其他排除上限的表达；不得把本段实际"
            "上下限用于任何其他源单元。"
        )
    detected_abbreviations = detect_clinical_abbreviations(source_text)
    if detected_abbreviations:
        system_prompt += (
            "\n【缩写保留规则】以下临床缩写在对应源单元的译文中必须原样"
            "出现。有“缩写优选中文”映射时，写作“映射中的中文全称（缩写）”；"
            "没有映射时仅保留源缩写，不得虚构中文全称。绝对不得在译文中输出"
            "“规范中文”“原缩略语”“映射中的中文全称”等规则占位文字："
            + "、".join(detected_abbreviations)
        )
        abbreviation_contract = render_preferred_abbreviation_contract(
            detected_abbreviations
        )
        if abbreviation_contract:
            system_prompt += f"\n【缩写优选中文】\n{abbreviation_contract}"
    if glossary and "\n" in glossary:
        system_prompt += (
            "\n【受控术语表】以下 english/preferred_zh 等字段是翻译约束；"
            "输出只能使用字段值形成自然中文，不得输出字段名或规则说明。\n"
            f"{glossary}"
        )
    elif glossary:
        system_prompt += f"\n术语表版本: {glossary}"
    request_payload = {
        "model": BODY_MODEL,
        "prompt_version": HY_MT2_PROMPT_VERSION,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0,
        "max_tokens": 4096,
    }
    input_hash = sha(
        json.dumps(request_payload, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":"))
    )
    body = json.dumps(
        {k: v for k, v in request_payload.items() if k != "prompt_version"}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    def _execute(_lease=None):
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read().decode("utf-8"))

    result = (
        run_gated_omlx_request(
            _execute, kind="translation",
            owner="medical-writing-api:translation-body",
        )
        if USE_OMLX_GATE
        else _execute()
    )
    usage = result.get("usage") or {}
    finish = (result.get("choices") or [{}])[0].get("finish_reason", "")
    translated = validate_completion_payload(result, BODY_MODEL)
    _CALL_LOG.append({
        "chunk_id": chunk_id,
        "correction": bool(correction_note),
        "source_chars": len(source_text),
        "output_chars": len(translated),
        "finish_reason": finish,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "output_sha256": sha(translated),
    })
    print(f"[hy-mt2] chunk={chunk_id} correction={bool(correction_note)} "
          f"out={len(translated)}ch finish={finish} "
          f"tokens={usage.get('completion_tokens')}")
    return HyMt2TranslationResult(
        chapter_id=chapter_id,
        chunk_id=chunk_id,
        translated_text=translated,
        translated_text_sha256=sha(translated),
        model=BODY_MODEL,
        prompt_version=HY_MT2_PROMPT_VERSION,
        input_hash=input_hash,
        output_hash=sha(translated),
    )


# ------------------------------------------------------- translate + fidelity
from app.chapter_translation_pipeline import FidelityBlockedError  # noqa: E402
from app.chapter_translation_pipeline import (  # noqa: E402
    parse_unit_delimited_output,
    normalize_post_hy_unit_output,
    strip_unit_markers,
)

chunk_reports = []
for spec in chunks:
    units = split_source_into_units(spec.source_text)
    glossary = render_regulatory_translation_glossary_contract(spec.source_text)
    blocked_codes: list[str] = []
    salvage_notes: dict[str, str] = {}
    try:
        hy_result, parsed = translate_units_with_bounded_correction(
            real_hy_mt2_translator,
            units=units,
            glossary=glossary or "cms_regulatory_zh_v1",
            chapter_id=CHAPTER,
            chunk_id=spec.chunk_id,
            read_only_context=spec.adjacent_context or "",
        )
    except FidelityBlockedError as exc:
        # Production blocks the chapter here.  This DIAGNOSTIC continues:
        # salvage the failed-unit fragment, translate the remaining units
        # one-by-one (single-unit requests), and hand the COMPLETE
        # candidate plus its unit-level findings to the medical gate.
        blocked_codes = list(exc.failure_codes)
        print(f"[blocked] chunk={spec.chunk_order} codes={blocked_codes}")
        parsed = {}
        failed = sorted({
            int(m.group(1))
            for m in (re.match(r"^unit_(\d+):", c) for c in blocked_codes)
            if m is not None
        })
        unit_by_ordinal = {u.ordinal: u for u in units}
        fragment_map, frag_errors = parse_unit_delimited_output(
            exc.last_output or "", expected_ordinals=failed or [])
        for ordinal in sorted(unit_by_ordinal):
            unit = unit_by_ordinal[ordinal]
            if ordinal in fragment_map and not frag_errors:
                parsed[ordinal] = normalize_post_hy_unit_output(
                    unit.text, fragment_map[ordinal])
                continue
            try:
                _r, _m = translate_units_with_bounded_correction(
                    real_hy_mt2_translator,
                    units=(unit,),
                    glossary=glossary or "cms_regulatory_zh_v1",
                    chapter_id=CHAPTER,
                    chunk_id=f"{spec.chunk_id}:diag_unit_{ordinal}",
                    read_only_context=spec.adjacent_context or "",
                )
                parsed[ordinal] = _m[ordinal]
            except FidelityBlockedError as unit_exc:
                # Keep the best fragment as the candidate; its codes are
                # the medical-judgment finding for this unit.
                unit_frag, unit_errs = parse_unit_delimited_output(
                    unit_exc.last_output or "", expected_ordinals=(ordinal,))
                if not unit_errs and ordinal in unit_frag:
                    parsed[ordinal] = normalize_post_hy_unit_output(
                        unit.text, unit_frag[ordinal])
                    salvage_mode = "marked_fragment"
                else:
                    raw = strip_unit_markers(
                        unit_exc.last_output or "").strip()
                    parsed[ordinal] = (
                        normalize_post_hy_unit_output(unit.text, raw)
                        if raw else "")
                    salvage_mode = "markerless_raw" if raw else "empty"
                salvage_notes[str(ordinal)] = salvage_mode
                print(f"[blocked-unit] chunk={spec.chunk_order} "
                      f"unit={ordinal} salvage={salvage_mode} "
                      f"codes={list(unit_exc.failure_codes)}")
    codes = list(evaluate_translation_fidelity_aligned_units(units, parsed))
    chunk_reports.append({
        "chunk_id": spec.chunk_id,
        "chunk_order": spec.chunk_order,
        "source_chars": len(spec.source_text),
        "translation_chars": len(reassemble_aligned_translation(units, parsed)),
        "unit_count": len(units),
        "fidelity_codes": codes,
        "blocked_during_production_path": blocked_codes,
        "unit_salvage_modes": salvage_notes,
        "aligned_translation": reassemble_aligned_translation(units, parsed),
    })
    print(f"[gate] chunk={spec.chunk_order} codes={codes}")

chapter_candidate = "\n\n".join(r["aligned_translation"] for r in chunk_reports)
report = {
    "command": "replay-truncation-fix",
    "span_id": SPAN_ID,
    "plan_id": PLAN_ID,
    "model": BODY_MODEL,
    "base_url": BASE_URL,
    "ensure_translation": ENSURE,
    "lifecycle_status": STATUS,
    "source_chars": len(SOURCE_TEXT),
    "chunk_count": len(chunks),
    "chunk_sizes": [len(c.source_text) for c in chunks],
    "old_blocked_fragment_chars": 146,
    "new_translation_chars": len(chapter_candidate),
    "model_calls": _CALL_LOG,
    "chunks": chunk_reports,
    "chapter_candidate": chapter_candidate,
    "zero_db_writes": True,
    "evidence_only": True,
}
OUT_DIR.mkdir(parents=True, exist_ok=True)
(OUT_DIR / "replay_result.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("[done] new translation chars:", len(chapter_candidate),
      "| fidelity codes:", {r["chunk_order"]: r["fidelity_codes"]
                            for r in chunk_reports})
