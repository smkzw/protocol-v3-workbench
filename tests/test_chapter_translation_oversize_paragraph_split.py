"""Truncation counterexample: a single over-limit paragraph must be split
before translation (round23 replay fix).

Real sample shape (NCT02176291, span wref_span_9669b181c91ae7a58c824426):
a 4865-char source that is ONE physical paragraph (zero newlines) entered
``build_chunks_from_plan`` and came out as exactly ONE chunk — the
``_split_oversized_text`` "indivisible line is kept intact" branch.  That
chunk then became one 8-unit model request whose output hit the provider
completion cap and collapsed to a 146-char fragment; the chapter blocked
with the fragment as its only persisted evidence.

Counterexamples proven here (zero model, deterministic pipeline only):

- RED→GREEN: the single-paragraph over-limit source must now yield MULTIPLE
  chunks, each within ``CHUNK_TARGET_CHARS``, at safe sentence boundaries,
  in document order, with every digit token and sentence preserved.
- Units: every translation unit inside every produced chunk stays within
  ``UNIT_TARGET_CHARS`` (or is a genuinely indivisible line).
- Regression guards: short text stays one chunk; structured multi-line
  oversize text splits exactly as before the fix; splitting is
  deterministic.
"""
from __future__ import annotations

import re
import unittest
from types import SimpleNamespace

from services.api.app.chapter_translation_pipeline import (
    CHUNK_TARGET_CHARS,
    UNIT_TARGET_CHARS,
    DocumentPlanResult,
    _split_oversized_text,
    build_chunks_from_plan,
    split_source_into_units,
)


def _sentence(index: int) -> str:
    """One deterministic sentence with numbers, doses and abbreviations."""
    return (
        f"Subjects in cohort {index} receive {5 * index}.5 mg of IMP{index} "
        f"(IMP{index} = investigational product) administered QD for "
        f"{index * 2} weeks, with EASI-{50 if index % 2 == 0 else 75} "
        f"assessed at Week {4 * index} and plasma levels below "
        f"{index}.0 ng/mL excluded (NCT{10000000 + index}). "
    )


def _oversize_single_paragraph(total_chars: int) -> str:
    parts: list[str] = []
    length = 0
    index = 1
    while length < total_chars:
        sentence = _sentence(index)
        parts.append(sentence)
        length += len(sentence)
        index += 1
    # One physical paragraph: no newlines at all.
    return "".join(parts)


SAMPLE_LIKE_TEXT = _oversize_single_paragraph(4865)

_PLAN = DocumentPlanResult(
    flash_plan=None,  # type: ignore[arg-type]
    chapters=(("ch_ovs", "Background", "", ("span_ovs",)),),
    document_role="protocol",
    ambiguity_codes=(),
)


def _build(text: str):
    span = SimpleNamespace(span_id="span_ovs", source_text=text)
    return build_chunks_from_plan(_PLAN, (span,))


def _chapter_chunks(text: str):
    chunks = []
    for entry in _build(text):
        for _key, chapter_chunks in entry.items():
            chunks.extend(chapter_chunks)
    return chunks


def _digit_multiset(text: str) -> list[str]:
    return sorted(re.findall(r"\d+", text))


def _prose(text: str) -> str:
    """Content signature ignoring the structural separators the splitter
    is allowed to introduce between segments."""
    return re.sub(r"\s+", "", text)


class OversizeParagraphSplitTests(unittest.TestCase):
    def test_single_overlimit_paragraph_yields_bounded_chunks(self):
        chunks = _chapter_chunks(SAMPLE_LIKE_TEXT)
        self.assertGreater(
            len(chunks), 1,
            "a 4865-char single paragraph must not collapse into one chunk "
            "(the truncation counterexample)",
        )
        for chunk in chunks:
            self.assertLessEqual(
                len(chunk.source_text), CHUNK_TARGET_CHARS,
                f"chunk {chunk.chunk_order} exceeds the target: "
                f"{len(chunk.source_text)}",
            )
        # Document order preserved: chunk_order ascending 1..N.
        self.assertEqual(
            list(range(1, len(chunks) + 1)),
            [chunk.chunk_order for chunk in chunks],
        )
        # No content lost: digits and prose content survive the split.
        self.assertEqual(
            _digit_multiset(SAMPLE_LIKE_TEXT),
            _digit_multiset("\n\n".join(c.source_text for c in chunks)),
        )
        self.assertEqual(
            _prose(SAMPLE_LIKE_TEXT),
            _prose("".join(c.source_text for c in chunks)),
        )

    def test_every_unit_inside_every_chunk_stays_bounded(self):
        chunks = _chapter_chunks(SAMPLE_LIKE_TEXT)
        for chunk in chunks:
            for unit in split_source_into_units(chunk.source_text):
                self.assertLessEqual(
                    len(unit.text), UNIT_TARGET_CHARS,
                    f"unit {unit.ordinal} of chunk {chunk.chunk_order} "
                    f"exceeds the unit target: {len(unit.text)}",
                )

    def test_splitting_is_deterministic(self):
        first = [
            (c.chunk_id, c.chunk_fingerprint, c.source_text)
            for c in _chapter_chunks(SAMPLE_LIKE_TEXT)
        ]
        second = [
            (c.chunk_id, c.chunk_fingerprint, c.source_text)
            for c in _chapter_chunks(SAMPLE_LIKE_TEXT)
        ]
        self.assertEqual(first, second)

    def test_short_text_stays_one_chunk(self):
        chunks = _chapter_chunks(_oversize_single_paragraph(500))
        self.assertEqual(1, len(chunks))

    def test_structured_multiline_oversize_still_splits_on_lines(self):
        # Three over-target physical lines (list/row shape): the pre-existing
        # line-boundary behavior must be unchanged by the paragraph fix.
        line = (
            "Subjects receive 10 mg daily for 4 weeks and the endpoint is "
            "assessed at Week 4 with plasma levels below 5.0 ng/mL excluded."
        )
        text = "\n".join(line for _ in range(40))
        self.assertGreater(len(text), CHUNK_TARGET_CHARS)
        pieces = _split_oversized_text(text, CHUNK_TARGET_CHARS)
        self.assertGreater(len(pieces), 1)
        for piece in pieces:
            self.assertLessEqual(len(piece), CHUNK_TARGET_CHARS)
        self.assertEqual(
            _digit_multiset(text),
            _digit_multiset("\n".join(pieces)),
        )


if __name__ == "__main__":
    unittest.main()
