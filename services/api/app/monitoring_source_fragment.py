from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .protocol_text_extractor import ProtocolTextDocument


def resolve_protocol_fragment(document: ProtocolTextDocument, locator: str) -> dict[str, Any]:
    paragraph_match = re.fullmatch(r"docx:paragraph:(\d+)", locator)
    if paragraph_match:
        paragraph_index = int(paragraph_match.group(1))
        paragraph_position = next(
            (
                index
                for index, paragraph in enumerate(document.paragraphs)
                if paragraph.paragraph_index == paragraph_index
                and paragraph.source_locator == locator
            ),
            None,
        )
        if paragraph_position is None:
            raise KeyError("protocol paragraph locator not found")
        paragraph = document.paragraphs[paragraph_position]
        before = [
            item.text
            for item in document.paragraphs[max(0, paragraph_position - 2) : paragraph_position]
            if item.text and not item.is_in_table
        ]
        after = [
            item.text
            for item in document.paragraphs[paragraph_position + 1 : paragraph_position + 3]
            if item.text and not item.is_in_table
        ]
        fragment = {
            "source_type": "protocol",
            "locator_kind": "paragraph",
            "locator": locator,
            "display_locator": f"方案段落 {paragraph_index + 1}",
            "index_base": 0,
            "text": paragraph.text,
            "fields": [],
            "context_before": before,
            "context_after": after,
        }
        fragment["primary_summary"] = _protocol_primary_summary(fragment)
        return fragment

    table_paragraph_match = re.fullmatch(
        r"docx:table:(\d+):row:(\d+):cell:(\d+):paragraph:(\d+)",
        locator,
    )
    if table_paragraph_match:
        table_index, row_index, cell_index, paragraph_index = map(
            int,
            table_paragraph_match.groups(),
        )
        paragraph = next(
            (
                item
                for item in document.paragraphs
                if item.source_locator == locator
            ),
            None,
        )
        if paragraph is None:
            raise KeyError("protocol table paragraph locator not found")
        fragment = {
            "source_type": "protocol",
            "locator_kind": "table_cell_paragraph",
            "locator": locator,
            "display_locator": (
                f"方案表 {table_index + 1}，第 {row_index + 1} 行，"
                f"第 {cell_index + 1} 列，第 {paragraph_index + 1} 段"
            ),
            "index_base": 0,
            "text": paragraph.text,
            "fields": [],
            "context_before": [],
            "context_after": [],
        }
        fragment["primary_summary"] = _protocol_primary_summary(fragment)
        return fragment

    table_match = re.fullmatch(r"docx:table:(\d+):row:(\d+)", locator)
    if table_match:
        table_index, row_index = map(int, table_match.groups())
        if table_index >= len(document.tables):
            raise KeyError("protocol table locator not found")
        table = document.tables[table_index]
        if row_index >= len(table.rows):
            raise KeyError("protocol table row locator not found")
        cells = [cell.text for cell in table.rows[row_index] if cell.text]
        fragment = {
            "source_type": "protocol",
            "locator_kind": "table_row",
            "locator": locator,
            "display_locator": f"方案表 {table_index + 1}，第 {row_index + 1} 行",
            "index_base": 0,
            "text": "；".join(cells),
            "fields": [
                {"field": f"列 {index + 1}", "value": _bounded_text(value)}
                for index, value in enumerate(cells)
            ],
            "context_before": [],
            "context_after": [],
        }
        fragment["primary_summary"] = _protocol_primary_summary(fragment)
        return fragment
    raise ValueError("unsupported protocol source locator")


def resolve_listing_fragment(
    public_listing_label: str,
    sheets: Mapping[str, Sequence[Mapping[str, Any]]],
    locator: str,
) -> dict[str, Any]:
    match = re.fullmatch(r"listing:(.+?):sheet:(.+):row:(\d+)", locator)
    if not match:
        raise ValueError("unsupported listing source locator")
    locator_label, sheet_name, row_text = match.groups()
    if locator_label != public_listing_label:
        raise KeyError("listing source label does not match current project source")
    row_index = int(row_text)
    if row_index < 1:
        raise KeyError("listing row locator must be one-based")
    rows = sheets.get(sheet_name)
    if rows is None or row_index > len(rows):
        raise KeyError("listing row locator not found")
    row = rows[row_index - 1]
    fields = [
        {"field": _bounded_text(key, 160), "value": _bounded_text(value)}
        for key, value in row.items()
        if str(value or "").strip()
    ][:80]
    fragment = {
        "source_type": "listing",
        "locator_kind": "sheet_row",
        "locator": locator,
        "display_locator": f"{sheet_name} · 第 {row_index} 条解析数据记录",
        "index_base": 1,
        "text": "",
        "fields": fields,
        "context_before": [],
        "context_after": [],
    }
    fragment["primary_summary"] = _listing_primary_summary(fields)
    return fragment


def _protocol_primary_summary(fragment: Mapping[str, Any]) -> str:
    text = _bounded_text(fragment.get("text", ""), 360)
    return f"方案原文：{text}" if text else "方案原文待读取。"


def _listing_primary_summary(fields: Sequence[Mapping[str, Any]]) -> str:
    values = {
        str(item.get("field", "")).strip().upper(): _bounded_text(item.get("value", ""), 240)
        for item in fields
        if str(item.get("field", "")).strip()
    }
    if _first(values, "LBTEST", "LBTESTCD"):
        return _laboratory_summary(values)
    domain = _first(values, "DOMAIN").upper()
    if domain.startswith("AE") or _first(values, "AETERM", "AEDECOD"):
        return _adverse_event_summary(values)
    if domain.startswith("CM") or _first(values, "CMTRT", "CMDECOD"):
        return _concomitant_medication_summary(values)
    if domain.startswith(("EX", "DA")) or _first(values, "EXDOSE", "EX2DOSE", "EX3DOSE"):
        return _investigational_product_summary(values)
    if domain.startswith("MH") or _first(values, "MHTERM", "MHDECOD"):
        return _medical_history_summary(values)
    return _generic_listing_summary(values)


def _laboratory_summary(values: Mapping[str, str]) -> str:
    date = _first(values, "LBDAT", "LBDTC", "LBDATE")
    visit = _visit_label(values)
    test = _first(values, "LBTEST", "LBTESTCD")
    result = _first(values, "LBORRES", "LBORRESN", "LBSTRESC", "LBSTRESN")
    unit = _first(values, "LBORRESU", "LBSTRESU")
    low = _first(values, "LBORNRLO", "LBSTNRLO")
    high = _first(values, "LBORNRHI", "LBSTNRHI")
    significance = _first(values, "LBCLSIGN", "LBSIG", "LBNRIND", "LBCOM")
    direction = _abnormal_direction(result, low, high)
    result_with_unit = f"{result} {unit}" if unit.startswith(("10^", "x10", "×10")) else f"{result}{unit}".strip()
    parts = [date, visit, test, result_with_unit]
    if low or high:
        parts.append(f"ref({_display_reference_bound(low)}, {_display_reference_bound(high)})")
    if direction:
        parts.append(direction)
    if significance:
        parts.append(significance)
    return " ".join(part for part in parts if part) or _generic_listing_summary(values)


def _adverse_event_summary(values: Mapping[str, str]) -> str:
    date_range = _date_range(values, ("AESTDAT", "AESTDTC"), ("AEENDAT", "AEENDTC"))
    visit = _visit_label(values)
    term = _first(values, "AETERM", "AEDECOD", "AEPT")
    grade = _first(values, "AETOXGR", "AESEV", "AEGRADE")
    serious = _first(values, "AESER", "AESERIOUS")
    relation = _first(values, "AEREL", "AERELNST", "AEREL1")
    outcome = _first(values, "AEOUT")
    details = [
        f"分级/程度 {grade}" if grade else "",
        f"严重性 {serious}" if serious else "",
        f"与试验药物关系 {relation}" if relation else "",
        f"转归 {outcome}" if outcome else "",
    ]
    primary = " ".join(part for part in [date_range, visit, term] if part)
    suffix = "；".join(part for part in details if part)
    return f"{primary}；{suffix}" if suffix else primary or _generic_listing_summary(values)


def _concomitant_medication_summary(values: Mapping[str, str]) -> str:
    date_range = _date_range(values, ("CMSTDAT", "CMSTDTC"), ("CMENDAT", "CMENDTC"))
    visit = _visit_label(values)
    medication = _first(values, "CMTRT", "CMDECOD")
    dose = _first(values, "CMDOSE", "CMDOSTXT")
    unit = _first(values, "CMDOSU")
    frequency = _first(values, "CMFREQ")
    route = _first(values, "CMROUTE")
    indication = _first(values, "CMINDC", "CMIND")
    regimen = " ".join(part for part in [f"{dose}{unit}".strip(), frequency, route] if part)
    summary = " ".join(part for part in [date_range, visit, "非试验用合并用药", medication, regimen] if part)
    return f"{summary}；用药原因 {indication}" if indication else summary or _generic_listing_summary(values)


def _investigational_product_summary(values: Mapping[str, str]) -> str:
    date_range = _date_range(
        values,
        ("EXSTDAT", "EXSTDTC", "EX2STDAT", "EX3STDAT", "DASTDAT"),
        ("EXENDAT", "EXENDTC", "EX2ENDAT", "EX3ENDAT", "DAENDAT"),
    )
    visit = _visit_label(values)
    treatment = _first(values, "EXTRT", "EX2TRT", "EX3TRT", "DATR") or "试验药物"
    dose = _first(values, "EXDOSE", "EX2DOSE", "EX3DOSE", "DADOSE")
    unit = _first(values, "EXDOSU", "EX2DOSU", "EX3DOSU", "DADOSU")
    frequency = _first(values, "EXDOSFRQ", "EXFRQ", "EX2FRQ", "EX3FRQ", "DAFREQ")
    route = _first(values, "EXROUTE", "EX2ROUTE", "EX3ROUTE", "DAROUTE")
    detail = _first(values, "EXDESC", "EX2DESC", "EX3DESC", "DACOM", "EXREAS")
    regimen = " ".join(part for part in [f"{dose}{unit}".strip(), frequency, route] if part)
    summary = " ".join(part for part in [date_range, visit, treatment, regimen] if part)
    return f"{summary}；用药记录：{detail}" if detail else summary or _generic_listing_summary(values)


def _medical_history_summary(values: Mapping[str, str]) -> str:
    date_range = _date_range(values, ("MHSTDAT", "MHSTDTC"), ("MHENDAT", "MHENDTC"))
    visit = _visit_label(values)
    term = _first(values, "MHTERM", "MHDECOD")
    ongoing = _first(values, "MHONGO", "MHENRTPT")
    summary = " ".join(part for part in [date_range, visit, "病史", term] if part)
    return f"{summary}；是否持续 {ongoing}" if ongoing else summary or _generic_listing_summary(values)


def _generic_listing_summary(values: Mapping[str, str]) -> str:
    ignored = {
        "__STUDYOID", "DOMAIN", "SITEID", "SITE", "SITENM", "USUBJID", "SUBJID",
        "FORM", "FORMNM", "FORMOID", "PAGE", "LINE", "RECREP", "FORMREP", "STATUS",
    }
    parts = [
        f"{key}={value}"
        for key, value in values.items()
        if value and key not in ignored
    ][:6]
    return "；".join(parts) if parts else "原始数据记录已定位，请查看完整原文。"


def _visit_label(values: Mapping[str, str]) -> str:
    candidates = [
        _first(values, "__STUDYEVENTOID", "VISTOID", "VISITNUM"),
        _first(values, "VISIT", "VISITNM"),
    ]
    output: list[str] = []
    for candidate in candidates:
        if not candidate or any(candidate in existing or existing in candidate for existing in output):
            continue
        output.append(candidate)
    return " ".join(output)


def _date_range(
    values: Mapping[str, str],
    start_fields: Sequence[str],
    end_fields: Sequence[str],
) -> str:
    start = _first(values, *start_fields)
    end = _first(values, *end_fields)
    if start and end and start != end:
        return f"{start}~{end}"
    return start or end


def _abnormal_direction(result: str, low: str, high: str) -> str:
    result_number = _numeric_value(result)
    low_number = _numeric_value(low)
    high_number = _numeric_value(high)
    if result_number is None:
        return ""
    if high_number is not None and result_number > high_number:
        return "↑"
    if low_number is not None and result_number < low_number:
        return "↓"
    return ""


def _numeric_value(value: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    return float(match.group(0)) if match else None


def _display_reference_bound(value: str) -> str:
    cleaned = re.sub(r"^(?:<=|>=|<|>)\s*", "", str(value or "").strip())
    return cleaned or "-"


def _first(values: Mapping[str, str], *fields: str) -> str:
    for field in fields:
        value = values.get(field.upper(), "")
        if value and value != ".":
            return value
    return ""


def _bounded_text(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else f"{text[: limit - 1]}…"
