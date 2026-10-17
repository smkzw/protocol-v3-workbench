"""确定性检查器族（WP-M3-CHECKERS）。

依据 plans/mw_reboot_20261017/03_WRITING_SYSTEM.md「检查器」与 eval/SCHEMAS.md §8：
- 事实一致：正文中的数字/剂量/组别/访视日/终点名与 StudyDefinition 事实比对；
- 风格泄漏：正文实体/数字与 StyleKit 范例比对，命中竞品药名、剂量、样本量即标记；
- 跨章一致：同一数值族在不同章节取值发散（确定性部分；异族模型复核不在本包）；
- 过程话术/占位：正则清单，只检测。

纪律（03_WRITING_SYSTEM「检查器」）：
- **只标记，不改写**。本模块没有任何改写/替换正文的函数；发现问题由上游
  带具体问题做定点重写（≤2 次）。禁止用正则替换模型正文中的数字。
- 输出条目形如 {"checker", "severity": "info|warn|fail", "detail"}，可直接
  写入 SectionDraft.checker_results；附加字段（kind/span/fact_path）为增量信息。
- 纯函数、纯标准库、确定性：无网络、无模型、无随机。

泛化红线：本模块不含任何具体药物/疾病/量表名/章号分支。所有项目实体
来自调用方数据（StudyDefinition 事实集、StyleKit、锚词表、allowlist）。
代码内置的只有通用机制：数字掩码指纹、通用单位表（mg/周/例……）、
通用过程话术正则与通用英文虚词停用表。

归一化约定：
- half_pack：全角折半、千分位逗号折叠、保留空白（用于单位对/实体词提取）；
- pack_text：在 half_pack 基础上把"数字 空白 数字"折叠为"数字⟨s⟩数字"再
  去空白（用于掩码指纹/锚词句），⟨s⟩ 防止相邻数字被去空白合并成一个数。

锚词机制说明：纯数字事实（如样本量、访视周）无法从值本身推断正文语境，
必须由调用方提供 fact_anchors（fact_path → 锚词列表，如"样本量"/"访视"），
锚词所在句内的数字才参与比对。锚词是数据不是代码，避免代码语义分支。

已知确定性边界（诚实声明，非缺陷）：中文数字（如"两百四十"）不支持；
无数字实体（如组别名改写）与语义级跨章矛盾由异族模型复核层覆盖。

CLI：
    python3 tools/writing/section_checkers.py --file 正文.txt --facts facts.json \
        [--stylekit stylekit.json] [--anchors anchors.json] [--allowlist a.json]

退出码：0 = 无 fail；1 = 存在 fail；2 = 用法/读取错误。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

__all__ = [
    "check_fact_consistency",
    "check_style_leakage",
    "check_cross_section_consistency",
    "check_process_talk",
    "run_section_checkers",
]

# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------

_FULLWIDTH_MAP = {
    ord("０"): "0", ord("１"): "1", ord("２"): "2", ord("３"): "3", ord("４"): "4",
    ord("５"): "5", ord("６"): "6", ord("７"): "7", ord("８"): "8", ord("９"): "9",
    ord("Ａ"): "a", ord("Ｂ"): "b", ord("Ｃ"): "c", ord("Ｄ"): "d", ord("Ｅ"): "e",
    ord("Ｆ"): "f", ord("Ｇ"): "g", ord("Ｈ"): "h", ord("Ｉ"): "i", ord("Ｊ"): "j",
    ord("Ｋ"): "k", ord("Ｌ"): "l", ord("Ｍ"): "m", ord("Ｎ"): "n", ord("Ｏ"): "o",
    ord("Ｐ"): "p", ord("Ｑ"): "q", ord("Ｒ"): "r", ord("Ｓ"): "s", ord("Ｔ"): "t",
    ord("Ｕ"): "u", ord("Ｖ"): "v", ord("Ｗ"): "w", ord("Ｘ"): "x", ord("Ｙ"): "y",
    ord("Ｚ"): "z",
    ord("ａ"): "a", ord("ｂ"): "b", ord("ｃ"): "c", ord("ｄ"): "d", ord("ｅ"): "e",
    ord("ｆ"): "f", ord("ｇ"): "g", ord("ｈ"): "h", ord("ｉ"): "i", ord("ｊ"): "j",
    ord("ｋ"): "k", ord("ｌ"): "l", ord("ｍ"): "m", ord("ｎ"): "n", ord("ｏ"): "o",
    ord("ｐ"): "p", ord("ｑ"): "q", ord("ｒ"): "r", ord("ｓ"): "s", ord("ｔ"): "t",
    ord("ｕ"): "u", ord("ｖ"): "v", ord("ｗ"): "w", ord("ｘ"): "x", ord("ｙ"): "y",
    ord("ｚ"): "z",
    ord("％"): "%", ord("，"): ",",
}

#: 数字-空白-数字 的分隔标记（防止去空白后相邻数字合并）。
#: 私有区字符：不是空白（\s 不吞）、不是文字（\w 不吞），真实正文不会出现。
_GAP = "\ue000"

_WHITESPACE_RE = re.compile(r"[\s\u3000]+")
_THOUSANDS_COMMA_RE = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_DIGIT_GAP_DIGIT_RE = re.compile(r"(\d)[\s\u3000]+(?=\d)")
_DIGIT_RUN_RE = re.compile(r"\d+(?:\.\d+)?")


def _fold(text: str) -> str:
    folded = (text or "").translate(_FULLWIDTH_MAP)
    return _THOUSANDS_COMMA_RE.sub("", folded)


def half_pack(text: str) -> str:
    """全角折半 + 千分位折叠 + 小写，保留空白（单位对/实体词提取用）。"""
    return _fold(text).casefold()


def pack_text(text: str) -> str:
    """在 half_pack 基础上先标记数字间隔再去空白（掩码指纹/锚词句用）。"""
    marked = _DIGIT_GAP_DIGIT_RE.sub(rf"\1{_GAP}", half_pack(text))
    return _WHITESPACE_RE.sub("", marked)


def _display(packed_fragment: str) -> str:
    return packed_fragment.replace(_GAP, " ")


def _digit_runs(packed: str) -> Tuple[str, ...]:
    return tuple(_DIGIT_RUN_RE.findall(packed))


def _to_floats(runs: Iterable[str]) -> List[float]:
    return [float(item) for item in runs]


def _mask(packed: str) -> str:
    return _DIGIT_RUN_RE.sub("#", packed)


def _cjk_count(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def _ascii_letter_count(text: str) -> int:
    return sum(1 for ch in text if ch.isascii() and ch.isalpha())


def _residue_strong(masked_value: str) -> bool:
    """强锚 = 数字以外的残留足够特异：≥2 个汉字或 ≥3 个 ASCII 字母。

    纯"数字+通用单位"（如 600 mg → 掩码 #mg）是弱锚：正文任何同单位数字
    都会命中掩码，只能降级为 warn，避免把文献引用剂量误判为事实冲突。
    """
    residue = masked_value.replace("#", "")
    return _cjk_count(residue) >= 2 or _ascii_letter_count(residue) >= 3


# ---------------------------------------------------------------------------
# 通用单位表（质量/时间/体积/百分比/计数；仅通用单位，无项目实体）
# ---------------------------------------------------------------------------

_UNIT_TABLE: Dict[str, Tuple[str, float]] = {}
for _unit, _factor in {
    "mg": 1.0, "毫克": 1.0, "g": 1000.0, "克": 1000.0,
    "ug": 0.001, "μg": 0.001, "µg": 0.001, "微克": 0.001, "kg": 1e6,
}.items():
    _UNIT_TABLE[_unit] = ("mass", _factor)
for _unit, _factor in {
    "day": 1.0, "days": 1.0, "d": 1.0, "天": 1.0, "日": 1.0,
    "week": 7.0, "weeks": 7.0, "w": 7.0, "wk": 7.0, "周": 7.0,
    "month": 30.0, "months": 30.0, "mo": 30.0, "月": 30.0,
    "year": 365.0, "years": 365.0, "y": 365.0, "年": 365.0,
}.items():
    _UNIT_TABLE[_unit] = ("time", _factor)
for _unit, _factor in {"ml": 1.0, "毫升": 1.0, "l": 1000.0, "升": 1000.0}.items():
    _UNIT_TABLE[_unit] = ("volume", _factor)
_UNIT_TABLE["%"] = ("percent", 1.0)
for _unit in ("例", "人", "名"):
    _UNIT_TABLE[_unit] = ("count", 1.0)

_UNIT_ALTERNATION = "|".join(sorted(_UNIT_TABLE.keys(), key=len, reverse=True))
_UNIT_PAIR_RE = re.compile(
    rf"(\d+(?:\.\d+)?)[\s\u3000]*({_UNIT_ALTERNATION})(?![a-z0-9])"
)


class _Pair:
    """一个"数字+单位"提及，归一到单位类的规范量纲。"""

    __slots__ = ("raw_number", "unit", "unit_class", "canonical")

    def __init__(self, raw_number: str, unit: str) -> None:
        self.raw_number = raw_number
        self.unit = unit
        unit_class, factor = _UNIT_TABLE[unit]
        self.unit_class = unit_class
        self.canonical = round(float(raw_number) * factor, 6)

    def key(self) -> Tuple[str, str, float]:
        return (self.unit_class, self.unit, self.canonical)

    def display(self) -> str:
        return f"{self.raw_number}{self.unit}"


def _pairs(half_packed: str) -> List[_Pair]:
    return [
        _Pair(match.group(1), match.group(2))
        for match in _UNIT_PAIR_RE.finditer(half_packed)
    ]


# ---------------------------------------------------------------------------
# 事实集展开
# ---------------------------------------------------------------------------

def _expand(path: str, value: Any) -> List[Tuple[str, Any]]:
    if isinstance(value, Mapping):
        out: List[Tuple[str, Any]] = []
        for key, item in value.items():
            out.extend(_expand(f"{path}.{key}", item))
        return out
    if isinstance(value, (list, tuple)):
        if not value:
            return []
        if all(not isinstance(item, (Mapping, list, tuple)) for item in value):
            # 扁平列表整体保留（组别、访视周等）：列表不是单一可断言值。
            return [(path, list(value))]
        out = []
        for item in value:
            out.extend(_expand(path, item))
        return out
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float, str)):
        return [(path, value)]
    return []


def _iter_fact_leaves(facts: Mapping[str, Any]) -> List[Tuple[str, Any]]:
    leaves: List[Tuple[str, Any]] = []
    for path, value in facts.items():
        leaves.extend(_expand(str(path), value))
    return leaves


def _finding(
    checker: str,
    severity: str,
    kind: str,
    detail: str,
    *,
    fact_path: Optional[str] = None,
    span: Optional[str] = None,
) -> Dict[str, str]:
    item: Dict[str, str] = {
        "checker": checker,
        "severity": severity,
        "kind": kind,
        "detail": _display(detail),
    }
    if fact_path:
        item["fact_path"] = fact_path
    if span:
        item["span"] = _display(span)
    return item


# ---------------------------------------------------------------------------
# 检查器 1：事实一致
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"[。；;！!？?\n]")


def check_fact_consistency(
    text: str,
    facts: Mapping[str, Any],
    *,
    fact_anchors: Optional[Mapping[str, Sequence[str]]] = None,
) -> List[Dict[str, str]]:
    """比对正文与 StudyDefinition 事实（确定性，只标记）。

    facts：扁平 fact_path → JSON 值（StudyDefinition.facts 形状）。
    fact_anchors：fact_path → 锚词列表；纯数字事实必须提供锚词才参与比对。
    """
    if not text or not facts:
        return []
    packed = pack_text(text)
    masked_text = _mask(packed)
    findings: List[Dict[str, str]] = []
    seen: Set[Tuple[str, str]] = set()

    for fact_path, value in _iter_fact_leaves(facts):
        if not isinstance(value, str):
            continue
        packed_value = pack_text(value)
        if not packed_value or not _DIGIT_RUN_RE.search(packed_value):
            continue  # 无数字实体：确定性只认精确出现，改名交给异族模型复核
        masked_value = _mask(packed_value)
        strong = _residue_strong(masked_value)
        if strong:
            if masked_value in masked_text:
                bad_runs = _occurrence_digit_runs_all(
                    packed, masked_text, masked_value
                )
                expected = _to_floats(_digit_runs(packed_value))
                offending = [runs for runs in bad_runs if _to_floats(runs) != expected]
                if offending:
                    if (fact_path, "value_conflict") not in seen:
                        seen.add((fact_path, "value_conflict"))
                        findings.append(_finding(
                            "fact_consistency", "fail", "value_conflict",
                            f"正文与事实不一致：{fact_path}={value!r}（事实数字 "
                            f"{_digit_runs(packed_value)}，正文出现 {offending[0]}）",
                            fact_path=fact_path,
                            span=masked_value,
                        ))
            continue
        # 弱锚值（纯"数字+通用单位"）：掩码会被正文任何同单位数字命中
        # （含文献引用剂量），仅在调用方提供该事实的锚词时才判断。
        if fact_anchors and fact_path in fact_anchors:
            findings.extend(
                _anchored_weak_pair_checks(
                    packed, fact_path, value, fact_anchors[fact_path], seen
                )
            )

    if fact_anchors:
        findings.extend(_anchored_numeric_checks(packed, facts, fact_anchors))
    return findings


def _anchored_weak_pair_checks(
    packed: str,
    fact_path: str,
    value: str,
    anchors: Sequence[str],
    seen: Set[Tuple[str, str]],
) -> List[Dict[str, str]]:
    """弱锚值（纯"数字+单位"）在锚词句内的数字/单位比对。"""
    value_pairs = _pairs(half_pack(value))
    if len(value_pairs) != 1:
        return []
    fact_pair = value_pairs[0]
    findings: List[Dict[str, str]] = []
    for anchor in anchors:
        anchor_packed = pack_text(str(anchor))
        segment = _segment_containing(packed, anchor_packed) if anchor_packed else None
        if segment is None:
            continue
        segment_pairs = _pairs(segment)
        same_class = [
            pair for pair in segment_pairs
            if pair.unit_class == fact_pair.unit_class
        ]
        canonicals = {pair.canonical for pair in same_class}
        raws = _segment_numbers(segment)
        if (
            raws
            and fact_pair.canonical not in canonicals
            and float(fact_pair.raw_number) not in raws
        ):
            if (fact_path, "anchored_number_conflict") not in seen:
                seen.add((fact_path, "anchored_number_conflict"))
                findings.append(_finding(
                    "fact_consistency", "fail", "anchored_number_conflict",
                    f"锚词“{_display(anchor_packed)}”句内数字与事实不一致："
                    f"{fact_path}={value!r}，句内数字 {raws}",
                    fact_path=fact_path,
                    span=anchor_packed,
                ))
        for pair in same_class:
            if (
                pair.unit != fact_pair.unit
                and float(pair.raw_number) == float(fact_pair.raw_number)
                and (fact_path, "unit_mismatch") not in seen
            ):
                seen.add((fact_path, "unit_mismatch"))
                findings.append(_finding(
                    "fact_consistency", "warn", "unit_mismatch",
                    f"正文单位与事实不一致：{fact_path}={value!r}，"
                    f"正文出现 {pair.display()}",
                    fact_path=fact_path,
                    span=pair.display(),
                ))
                break
        if findings:
            break
    return findings


def _occurrence_digit_runs(
    packed: str, masked: str, needle: str
) -> Tuple[str, ...]:
    """取掩码首个命中窗口内的正文数字串（packed 与 masked 逐段对齐）。"""
    all_runs = _occurrence_digit_runs_all(packed, masked, needle)
    return all_runs[0] if all_runs else ()


def _occurrence_digit_runs_all(
    packed: str, masked: str, needle: str
) -> List[Tuple[str, ...]]:
    """取掩码全部命中窗口内的正文数字串（packed 与 masked 逐段对齐）。"""
    if needle not in masked:
        return []
    runs_by_hit: List[Tuple[str, ...]] = []
    hit_start = masked.find(needle)
    hit_end = hit_start + len(needle)
    current: List[str] = []
    p_index = 0
    m_index = 0
    for match in _DIGIT_RUN_RE.finditer(packed):
        run_start, run_end = match.span()
        m_index += len(packed[p_index:run_start])
        if hit_start <= m_index < hit_end:
            current.append(match.group(0))
        elif m_index >= hit_end and current:
            runs_by_hit.append(tuple(current))
            current = []
            nxt = masked.find(needle, hit_end)
            if nxt < 0:
                break
            hit_start, hit_end = nxt, nxt + len(needle)
            if hit_start <= m_index < hit_end:
                current.append(match.group(0))
        m_index += 1
        p_index = run_end
    if current:
        runs_by_hit.append(tuple(current))
    return runs_by_hit


def _anchored_numeric_checks(
    packed: str,
    facts: Mapping[str, Any],
    fact_anchors: Mapping[str, Sequence[str]],
) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    for fact_path, anchors in fact_anchors.items():
        if fact_path not in facts:
            continue
        value = facts[fact_path]
        numbers: List[float]
        is_set = isinstance(value, (list, tuple))
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            numbers = [float(value)]
        elif is_set:
            numbers = [
                float(item)
                for item in value
                if isinstance(item, (int, float)) and not isinstance(item, bool)
            ]
        else:
            continue
        if not numbers:
            continue
        for anchor in anchors:
            anchor_packed = pack_text(str(anchor))
            if not anchor_packed:
                continue
            segment = _segment_containing(packed, anchor_packed)
            if segment is None:
                continue
            candidates = _segment_numbers(segment)
            if not candidates:
                continue
            if is_set:
                allowed = set(numbers)
                bad = [n for n in candidates if n not in allowed]
                if bad and (fact_path, "anchored_set_conflict") not in seen:
                    seen.add((fact_path, "anchored_set_conflict"))
                    findings.append(_finding(
                        "fact_consistency", "fail", "anchored_set_conflict",
                        f"锚词“{_display(anchor_packed)}”句内数字 {bad} 不属于事实集合 "
                        f"{fact_path}={value!r}",
                        fact_path=fact_path,
                        span=anchor_packed,
                    ))
            elif float(value) not in candidates:
                if (fact_path, "anchored_number_conflict") not in seen:
                    seen.add((fact_path, "anchored_number_conflict"))
                    findings.append(_finding(
                        "fact_consistency", "fail", "anchored_number_conflict",
                        f"锚词“{_display(anchor_packed)}”句内数字 {candidates} 与事实 "
                        f"{fact_path}={value!r} 不一致",
                        fact_path=fact_path,
                        span=anchor_packed,
                    ))
    return findings


def _segment_containing(packed: str, anchor: str) -> Optional[str]:
    for segment in _SENTENCE_SPLIT_RE.split(packed):
        if anchor in segment:
            return segment
    return None


def _segment_numbers(segment: str) -> List[float]:
    """锚词句内参与比对的数字：单位对数字 + ≥3 位裸数字。

    排除无单位短数字（如"指标甲75"的 75），防止列表锚词比对误报。
    """
    values: List[float] = [float(pair.raw_number) for pair in _pairs(segment)]
    values.extend(float(run) for run in _DIGIT_RUN_RE.findall(segment) if len(run) >= 3)
    return sorted(set(values))


# ---------------------------------------------------------------------------
# 检查器 2：风格泄漏
# ---------------------------------------------------------------------------

# 通用 ASCII 停用词：单位/给药频次缩写与英文虚词。不含任何量表名。
_GENERIC_ASCII_TOKENS = frozenset({
    "mg", "g", "ug", "kg", "ml", "l", "qd", "bid", "tid", "qw", "q2w", "q4w",
    "sc", "iv", "im", "po", "and", "the", "for", "with", "of", "in", "to",
    "vs", "versus", "patients", "received", "randomized", "randomised",
    "double", "blind", "blinded", "placebo", "group", "groups", "dose",
    "doses", "dosing", "oral", "once", "daily", "twice", "weekly",
    "administered", "administration", "treatment", "study", "studies",
    "trial", "trials", "phase", "subjects", "participants", "adults",
    "safety", "efficacy", "primary", "secondary", "endpoint", "endpoints",
    "objective", "objectives", "purpose", "methods", "results",
    "conclusion", "conclusions", "background", "total", "number",
    "percent", "ae", "sae", "susar", "ich", "gcp", "ema", "fda",
})

_ASCII_TOKEN_RE = re.compile(r"[a-z][a-z0-9\-–]{2,}")


def _entity_tokens(half_packed: str) -> Set[str]:
    return {
        token for token in _ASCII_TOKEN_RE.findall(half_packed)
        if token not in _GENERIC_ASCII_TOKENS
    }


class _OwnInventory:
    """本项目事实中已出现的实体/数字（泄漏豁免集）。"""

    __slots__ = ("tokens", "pair_keys", "numbers", "string_values")

    def __init__(self, facts: Mapping[str, Any]) -> None:
        self.tokens: Set[str] = set()
        self.pair_keys: Set[Tuple[str, str, float]] = set()
        self.numbers: Set[float] = set()
        self.string_values: List[str] = []
        for _, value in _iter_fact_leaves(facts):
            if isinstance(value, str):
                half_value = half_pack(value)
                self.string_values.append(pack_text(value))
                self.tokens |= _entity_tokens(half_value)
                for pair in _pairs(half_value):
                    self.pair_keys.add(pair.key())
                self.numbers.update(float(run) for run in _DIGIT_RUN_RE.findall(half_value))
            elif isinstance(value, (int, float)):
                self.numbers.add(float(value))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, bool):
                        continue
                    if isinstance(item, (int, float)):
                        self.numbers.add(float(item))
                    elif isinstance(item, str):
                        self.tokens |= _entity_tokens(half_pack(item))
                        self.numbers.update(
                            float(run) for run in _DIGIT_RUN_RE.findall(half_pack(item))
                        )


def check_style_leakage(
    text: str,
    stylekit: Optional[Mapping[str, Any]],
    facts: Mapping[str, Any],
    *,
    allowlist: Optional[Sequence[str]] = None,
) -> List[Dict[str, str]]:
    """正文实体/数字与 StyleKit 范例比对（确定性，只标记）。

    stylekit：SCHEMAS.md §3 的 StyleKit JSON（或 None）。
    命中竞品药名（范例 ASCII 实体 / competitor_names）、剂量、样本量即标记
    fail；本项目事实中已出现的实体与数字不标记。
    """
    if not text or not stylekit:
        return []
    examples: List[str] = []
    for items in (stylekit.get("per_node_examples") or {}).values():
        for item in items or []:
            if isinstance(item, Mapping) and item.get("text"):
                examples.append(str(item["text"]))
    if not examples:
        return []

    allow = {pack_text(str(item)) for item in (allowlist or []) if str(item)}
    own = _OwnInventory(facts)

    competitor_tokens: Set[str] = set()
    example_pair_keys: Set[Tuple[str, str, float]] = set()
    example_numbers: Set[float] = set()
    for example in examples:
        half_example = half_pack(example)
        competitor_tokens |= _entity_tokens(half_example)
        for pair in _pairs(half_example):
            example_pair_keys.add(pair.key())
        example_numbers.update(float(run) for run in _DIGIT_RUN_RE.findall(half_example))

    findings: List[Dict[str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    half_text = half_pack(text)

    # 竞品实体：范例中的 ASCII 实体词出现在正文，且不是本项目实体。
    for match in _ASCII_TOKEN_RE.finditer(half_text):
        token = match.group(0)
        if token in _GENERIC_ASCII_TOKENS or token not in competitor_tokens:
            continue
        if token in own.tokens:
            continue
        if any(token in entry or entry in token for entry in allow):
            continue
        if ("competitor_entity", token) in seen:
            continue
        seen.add(("competitor_entity", token))
        original = _fold(text)[match.start():match.end()]
        findings.append(_finding(
            "style_leakage", "fail", "competitor_entity",
            f"正文出现 StyleKit 范例实体 {original!r}（疑似竞品药名/代号泄漏）",
            span=original,
        ))

    # 声明式竞品名（可含中文）：StyleKit.competitor_names 数据字段。
    for name in (stylekit.get("competitor_names") or []):
        name_packed = pack_text(str(name))
        if not name_packed or name_packed not in pack_text(text):
            continue
        if any(name_packed in own_value for own_value in own.string_values):
            continue
        if any(name_packed in entry or entry in name_packed for entry in allow):
            continue
        if ("competitor_entity", name_packed) in seen:
            continue
        seen.add(("competitor_entity", name_packed))
        findings.append(_finding(
            "style_leakage", "fail", "competitor_entity",
            f"正文出现 StyleKit 声明的竞品实体 {str(name)!r}",
            span=str(name),
        ))

    # 竞品数值：范例中的数字+单位对原样出现在正文，且不是本项目数值。
    for pair in _pairs(half_text):
        if pair.key() in example_pair_keys and (
            pair.key() not in own.pair_keys
            and float(pair.raw_number) not in own.numbers
        ):
            if ("competitor_number_unit", pair.display()) not in seen:
                seen.add(("competitor_number_unit", pair.display()))
                findings.append(_finding(
                    "style_leakage", "fail", "competitor_number_unit",
                    f"正文出现范例数值 {pair.display()}（竞品剂量/数值泄漏）",
                    span=pair.display(),
                ))

    # 竞品裸数字（样本量等）：范例中 ≥10 的数字原样出现在正文，且不是
    # 本项目任何事实数字。
    text_numbers = {float(run) for run in _DIGIT_RUN_RE.findall(half_text)}
    text_numbers.update(float(pair.raw_number) for pair in _pairs(half_text))
    for number in sorted(text_numbers):
        if number < 10 or number in own.numbers or number not in example_numbers:
            continue
        if ("competitor_number", f"{number:g}") in seen:
            continue
        seen.add(("competitor_number", f"{number:g}"))
        findings.append(_finding(
            "style_leakage", "fail", "competitor_number",
            f"正文数字 {number:g} 与 StyleKit 范例数字一致（疑似样本量/计数泄漏）",
            span=f"{number:g}",
        ))
    return findings


# ---------------------------------------------------------------------------
# 检查器 3：跨章一致（确定性部分）
# ---------------------------------------------------------------------------

_TEMPLATE_WINDOW = 6


def _section_text(section: Mapping[str, Any]) -> str:
    for key in ("text", "proposal_text"):
        value = section.get(key)
        if isinstance(value, str):
            return value
    return ""


def check_cross_section_consistency(
    sections: Sequence[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    """同一数值族在不同章节取值发散即标记（确定性，只标记）。

    机制：把每章正文按数字串切片，取数字串前后各 6 字的上下文模板；
    同一模板在不同章节取到不同数字 → 发散。日期形数字（年/月/日）跳过。
    语义级矛盾（目的↔终点↔SoA↔统计的语义关联）由异族模型复核层覆盖，
    本检查器只提供确定性底座。
    """
    if len(sections) < 2:
        return []
    families: Dict[Tuple[str, str], Dict[str, float]] = {}
    for section in sections:
        section_id = str(section.get("section_id", ""))
        half = half_pack(_section_text(section))
        if not half:
            continue
        for match in _DIGIT_RUN_RE.finditer(half):
            run = match.group(0)
            start, end = match.span()
            prev_tail = half[max(0, start - _TEMPLATE_WINDOW):start]
            next_head = half[end:end + _TEMPLATE_WINDOW]
            if _is_calendar_shaped(prev_tail, next_head):
                continue
            if (
                _cjk_count(prev_tail + next_head) < 2
                and _ascii_letter_count(prev_tail + next_head) < 3
            ):
                continue  # 上下文太弱，不构成可判定的数值族
            families.setdefault((prev_tail, next_head), {}).setdefault(
                section_id, float(run)
            )

    findings: List[Dict[str, str]] = []
    for (prev_tail, next_head), values_by_section in families.items():
        distinct = sorted(set(values_by_section.values()))
        if len(distinct) < 2 or len(values_by_section) < 2:
            continue
        parts = [
            f"{sid}:{value:g}" for sid, value in sorted(values_by_section.items())
        ]
        findings.append(_finding(
            "cross_section_consistency", "fail", "cross_section_value_divergence",
            f"同一数值族在不同章节取值发散（上下文 …{prev_tail}⟨数字⟩{next_head}…）："
            + "；".join(parts),
            span=f"{prev_tail}⟨⟩{next_head}",
        ))
    return findings


def _is_calendar_shaped(prev_tail: str, next_head: str) -> bool:
    """年/月/日形状的数字串多为日期，不构成跨章事实，跳过。"""
    if next_head.lstrip().startswith("年"):
        return True
    if next_head.lstrip().startswith("月") and prev_tail.rstrip().endswith("年"):
        return True
    if next_head.lstrip().startswith("日") and (
        prev_tail.rstrip()[-2:].find("月") >= 0 or prev_tail.rstrip().endswith("年")
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# 检查器 4：过程话术/占位（正则清单，只检测）
# ---------------------------------------------------------------------------

_DEFAULT_PATTERNS: Tuple[Tuple[str, str, str, str], ...] = (
    ("placeholder_marker", r"【[^】]{0,12}(?:待补|待确认|待定|占位)[^】]{0,12}】", "placeholder", "fail"),
    ("placeholder_word", r"待补齐|待确认|待补充|待定(?!义)", "placeholder", "fail"),
    ("placeholder_latin", r"(?<![a-z0-9])(?:tbd|todo|fixme|xxx|n/a)(?![a-z0-9])|placeholder|lorem ipsum", "placeholder", "fail"),
    ("process_deferral", r"将在正式文本中|将在后续章节中|正式文本中明确|此处省略|以下省略|内容略", "process_talk", "warn"),
    ("process_self", r"作为ai|ai语言模型|由ai(?:生成|撰写|创建|输出)|我无法|我不能确定", "process_talk", "warn"),
    ("process_source_meta", r"根据(?:所)?提供(?:的)?(?:资料|信息|文档|文本)|依据(?:所)?提供(?:的)?|由于(?:相关)?(?:资料|信息|参考)(?:有限|不足|缺失)", "process_talk", "warn"),
    ("process_uncertain", r"暂(?:时)?(?:无法|不能)确定|尚无法核实|需进一步(?:确认|核实|补充)(?:信息|资料|后)", "process_talk", "warn"),
    ("engineering_artifact", r"```|\"section_id\"|\"proposal_text\"|\"semantic_node_id\"|\"checker_results\"", "engineering_artifact", "warn"),
)

_CONTEXT_WIDTH = 16


def _context(text: str, start: int, end: int) -> str:
    left = text[max(0, start - _CONTEXT_WIDTH):start]
    right = text[end:end + _CONTEXT_WIDTH]
    return f"…{left}【{text[start:end]}】{right}…"


def check_process_talk(
    text: str,
    *,
    extra_patterns: Optional[Sequence[Mapping[str, str]]] = None,
) -> List[Dict[str, str]]:
    """过程话术/占位检测（通用正则清单，只标记，不改写）。"""
    if not text:
        return []
    patterns: List[Tuple[str, "re.Pattern[str]", str, str]] = []
    for pattern_id, regex, kind, severity in _DEFAULT_PATTERNS:
        patterns.append((pattern_id, re.compile(regex, re.IGNORECASE), kind, severity))
    for extra in extra_patterns or []:
        patterns.append((
            str(extra.get("id", "extra")),
            re.compile(str(extra.get("pattern", "")), re.IGNORECASE),
            str(extra.get("kind", "process_talk")),
            str(extra.get("severity", "warn")),
        ))

    findings: List[Dict[str, str]] = []
    seen: Set[Tuple[str, int]] = set()
    matches: List[Tuple[str, "re.Match[str]", str, str]] = []
    for pattern_id, regex, kind, severity in patterns:
        for match in regex.finditer(text):
            key = (pattern_id, match.start())
            if key in seen:
                continue
            seen.add(key)
            matches.append((pattern_id, match, kind, severity))
    # 同 kind 命中互为包含时只留最外层（如【待补齐】不再重复报"待补齐"）；
    # 完全同位的命中按规则顺序保留首个。
    def _covered(index: int) -> bool:
        _, match, kind, _ = matches[index]
        for other_index, (_, other, other_kind, _) in enumerate(matches):
            if other_index == index or other_kind != kind:
                continue
            if other.start() <= match.start() and match.end() <= other.end():
                if (
                    other.start() < match.start()
                    or match.end() < other.end()
                    or other_index < index
                ):
                    return True
        return False

    matches = [item for index, item in enumerate(matches) if not _covered(index)]
    for pattern_id, match, kind, severity in matches:
        findings.append(_finding(
            "process_talk", severity, kind,
            f"{pattern_id}：{_context(text, match.start(), match.end())}",
            span=match.group(0),
        ))
    findings.sort(key=lambda item: (item.get("span", ""), item["kind"]))
    return findings


# ---------------------------------------------------------------------------
# 汇总入口
# ---------------------------------------------------------------------------

def run_section_checkers(
    text: str,
    facts: Mapping[str, Any],
    stylekit: Optional[Mapping[str, Any]] = None,
    *,
    fact_anchors: Optional[Mapping[str, Sequence[str]]] = None,
    allowlist: Optional[Sequence[str]] = None,
    extra_patterns: Optional[Sequence[Mapping[str, str]]] = None,
) -> List[Dict[str, str]]:
    """单节检查器汇总，输出可直接写入 SectionDraft.checker_results。"""
    results: List[Dict[str, str]] = []
    results.extend(check_fact_consistency(text, facts, fact_anchors=fact_anchors))
    if stylekit is not None:
        results.extend(check_style_leakage(text, stylekit, facts, allowlist=allowlist))
    results.extend(check_process_talk(text, extra_patterns=extra_patterns))
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="确定性检查器族（只标记不改写）")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--text")
    source.add_argument("--stdin", action="store_true")
    parser.add_argument("--facts", type=Path, required=True, help="StudyDefinition 事实 JSON")
    parser.add_argument("--stylekit", type=Path, default=None, help="StyleKit JSON")
    parser.add_argument("--anchors", type=Path, default=None, help="fact_anchors JSON")
    parser.add_argument("--allowlist", type=Path, default=None, help="泄漏豁免词 JSON 数组")
    args = parser.parse_args(argv)

    try:
        text = (
            args.file.read_text(encoding="utf-8")
            if args.file is not None
            else sys.stdin.read() if args.stdin else args.text or ""
        )
        facts = _load_json(args.facts)
        stylekit = _load_json(args.stylekit) if args.stylekit else None
        anchors = _load_json(args.anchors) if args.anchors else None
        allowlist = _load_json(args.allowlist) if args.allowlist else None
    except (OSError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2

    if not isinstance(facts, dict):
        print(
            json.dumps({"error": "--facts 必须是扁平事实对象"}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2

    results = run_section_checkers(
        text, facts, stylekit,
        fact_anchors=anchors, allowlist=allowlist,
    )
    fail_count = sum(1 for item in results if item["severity"] == "fail")
    report = {
        "checker_results": results,
        "counts": {
            "total": len(results),
            "fail": fail_count,
            "warn": sum(1 for item in results if item["severity"] == "warn"),
            "info": sum(1 for item in results if item["severity"] == "info"),
        },
        "pass": fail_count == 0,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
