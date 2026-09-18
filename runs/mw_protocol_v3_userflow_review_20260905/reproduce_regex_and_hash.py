"""Deterministic actual-code checks for mw_protocol_v3_userflow_review_20260905.

Read-only: imports the real production modules and exercises the exact code
expressions used by MedicalWritingFullDraftService._target_sections / .adopt
and ai_task_runner full-draft validation. No service, browser, or model run.

Check A (adopt precondition hash mismatch):
  _target_sections computes body_sha256 over _body_text(writable) — the
  "\n"-join of ALL non-empty paragraph body blocks — while .adopt compares it
  against sha256 of ONLY the first body block's text (target["body_block_id"]
  -> writable[0]). Any target section with >=2 non-empty paragraph blocks
  therefore fails adopt's staleness check with zero user edits.

Check B (UNRESOLVED_DRAFT_MARKER_RE false positive):
  The alternative "(?:未提供|未给出|未明确)(?:具体|数值|正式)?[^。；，,\r\n]{0,18}
  (?:参数|数据|资料|数值|条目)?" has an OPTIONAL trailing group, so it reduces
  to "未提供 + up to 18 arbitrary chars". It matches the standard GCP
  exclusion phrasing from the approved amendment's counterexample, which
  blocks full-draft generation (ai_task_runner.py:2708) and adoption
  (medical_writing_full_draft.py:696).
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "api"))
sys.path.insert(0, str(REPO / "packages"))
sys.path.insert(0, str(REPO))

from app.medical_writing_content_quality import UNRESOLVED_DRAFT_MARKER_RE  # noqa: E402
from app.medical_writing_full_draft import (  # noqa: E402
    FULL_DRAFT_MINIMUM_BODY_CHARS,
    _body_blocks,
    _body_text,
    _is_substantive,
)

results: list[tuple[str, bool, str]] = []

# ---- Check A: adopt hash precondition vs multi-block target sections ----
blocks_two_paragraphs = [
    {"block_type": "paragraph", "block_id": "b1", "text": "研究人群：成年受试者。"},
    {"block_type": "paragraph", "block_id": "b2", "text": "签署知情同意书。"},
    {"block_type": "heading", "block_id": "h1", "text": "章节标题"},
]
writable = _body_blocks(blocks_two_paragraphs)
body = _body_text(writable)
target_side_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()  # _target_sections line ~162
first = writable[0]  # body_block_id = writable[0]["block_id"], line ~153
adopt_side_text = str(first.get("text") or "").strip()  # adopt lines ~707: _text(blocks[body_index].get("text"))
adopt_side_hash = hashlib.sha256(adopt_side_text.encode("utf-8")).hexdigest()
substantive = _is_substantive(body)
results.append((
    "A1: two-paragraph non-substantive section qualifies as full-draft target",
    substantive is False,
    f"body={body!r} len={len(body)} < {FULL_DRAFT_MINIMUM_BODY_CHARS} -> _is_substantive={substantive}",
))
results.append((
    "A2: adopt-side first-block hash != target-side joined hash (false staleness, zero edits)",
    target_side_hash != adopt_side_hash,
    f"target_sha={target_side_hash[:12]}... adopt_sha={adopt_side_hash[:12]}...",
))
blocks_single_paragraph = [
    {"block_type": "paragraph", "block_id": "b1", "text": "短正文占位，不足以构成实质内容的正文段落。"},
]
writable1 = _body_blocks(blocks_single_paragraph)
body1 = _body_text(writable1)
h1_t = hashlib.sha256(body1.encode("utf-8")).hexdigest()
h1_a = hashlib.sha256(str(writable1[0].get("text") or "").strip().encode("utf-8")).hexdigest()
results.append((
    "A3 (control): single-paragraph target hashes agree",
    h1_t == h1_a,
    f"equal={h1_t == h1_a}",
))

# ---- Check B: unresolved-draft-marker false positives on legitimate prose ----
cases = [
    "筛选前未提供书面知情同意者不进入筛选。",
    "未能提供当前有效的诊断证明文件的受试者不纳入。",
    "未提供既往抗肿瘤治疗记录者须复核后方可入组。",
    "尚无直接证据支持该药物在此人群中的疗效，故本研究将探索其有效性。",
]
for text in cases:
    matched = bool(UNRESOLVED_DRAFT_MARKER_RE.search(text))
    results.append((f"B: regex flags legitimate protocol prose: {text}", matched,
                    f"UNRESOLVED_DRAFT_MARKER_RE.search -> {matched}"))
# Control: genuinely unresolved drafting language still flagged
control_pending = "本章节内容待确认。"
results.append((
    "B-control: genuine pending marker still flagged",
    bool(UNRESOLVED_DRAFT_MARKER_RE.search(control_pending)),
    "待确认 must stay flagged",
))
# Boundary count for the degenerate alternative
alt = re.compile(r"(?:未提供|未给出|未明确)(?:具体|数值|正式)?[^。；，,\r\n]{0,18}(?:参数|数据|资料|数值|条目)?")
long_tail = "未提供" + "药" * 19
results.append((
    "B-boundary: '未提供'+19 chars no longer matches (window is 18)",
    not alt.search(long_tail),
    f"alt.search('未提供'+19药)={bool(alt.search(long_tail))}",
))

# ---- Report ----
failed = 0
for name, expected, detail in results:
    status = "PASS(符合预期复现)" if expected else "FAIL(未复现)"
    if not expected:
        failed += 1
    print(f"[{status}] {name}\n         {detail}")
print(f"\n{len(results)} checks, {failed} failed-to-reproduce")
sys.exit(0 if failed == 0 else 1)
