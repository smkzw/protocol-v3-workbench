"""Text findings do not certify medical correctness or native Word formatting."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict

from ...medical_writing_content_quality import iter_unresolved_draft_markers
from ..registries.chapters import CheckerFinding


class TextUnit(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    text: str
    locator: str
    role: Literal['body', 'table_cell', 'header', 'footer', 'reference_title',
                  'source_quote', 'template_instruction', 'signature_control'] = 'body'
    source_locator: str = ''


def load_library(path: Path | None = None) -> dict:
    source = path or Path(__file__).resolve().parents[5] / 'config/medical_writing/protocol_v3/terminology.json'
    return json.loads(source.read_text())


def scan_text_units(units: Iterable[TextUnit], *, library: dict | None = None) -> tuple[CheckerFinding, ...]:
    rules = library if library is not None else load_library()
    findings = []
    for unit in units:
        def add(code: str, message: str, severity: str = 'warning', match: re.Match | None = None) -> None:
            location = unit.locator if match is None else f'{unit.locator}:chars:{match.start()}-{match.end()}'
            findings.append(CheckerFinding(code=code, severity=severity, location=location, message=message))

        if unit.role == 'template_instruction' and unit.text.strip():
            add('template_instruction_leak', '模板填写说明仍在最终文稿中，需要转为实质内容或从正文排除。', 'error')
        if unit.role in {'reference_title', 'source_quote'}:
            if not unit.source_locator.strip():
                add('quote_source_missing', '引用片段缺少原文定位。', 'error')
            # Original wording remains intact. This is not a whole-block bypass
            # for drafting instructions appended beside a quotation.
        else:
            for term in rules['preferred_terms']:
                for match in re.finditer(re.escape(term['variant']), unit.text):
                    add(term['code'], f"新正文建议使用“{term['preferred']}”；原文不会自动替换。", match=match)
            for rule in rules['format_rules']:
                for match in re.finditer(rule['pattern'], unit.text):
                    add(rule['code'], rule['message'], match=match)
        for match in iter_unresolved_draft_markers(unit.text):
            add('unresolved_draft_marker', '仍有草稿指令，需要补齐研究事实并写入实质内容。', 'error', match)
    return tuple(findings)


def abbreviation_inventory(units: Iterable[TextUnit], *, candidates: Iterable[str], definitions: Mapping[str, str]) -> dict:
    """Locate known candidates in actual prose, without guessing expansions."""
    material = [u for u in units if u.role in {'body', 'table_cell', 'header', 'footer'}]
    used = {}
    for token in sorted(set(candidates) | set(definitions)):
        if not token:
            continue
        pattern = re.compile(r'(?<![A-Za-z0-9])' + re.escape(token) + r'(?![A-Za-z0-9])')
        locations = list(dict.fromkeys(u.locator for u in material if pattern.search(u.text)))
        if locations:
            used[token] = locations
    return {
        'used': used,
        'missing_definitions': sorted(token for token in used if not definitions.get(token, '').strip()),
        'unused_definitions': sorted(set(definitions) - set(used)),
        'full_form_review': 'not_performed',
    }
