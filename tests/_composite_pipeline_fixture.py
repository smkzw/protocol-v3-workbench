"""Deterministic composite chapter-translation pipeline fixture for tests.

Provides a :class:`ChapterTranslationPipeline` wired to in-process fakes for
the three external stages (Flash plan, Hy-MT2 body, Flash QC) so that
``WritingReferenceTranslationService`` can exercise its authoritative
composite path without touching the network.

The fixture is behavior-compatible with the legacy ``FakeTranslationRunner``
used by the service/batch tests: callers can pass a ``translations`` map
(source_text -> translated_text) and the Hy-MT2 fake will emit the matching
candidate, while the Flash QC fake integrates it verbatim.  ``blocked_spans``
and ``failures_remaining`` reproduce the legacy runner's drift/failure knobs.

The Hy-MT2 fake also keeps a ``calls`` list (by chunk_id / span_id) so tests
that previously asserted on ``runner.calls`` keep working unchanged — the
batch test wires the same list onto ``runner.calls`` for backward
compatibility (see ``wire_pipeline_calls_to_runner``).
"""
from __future__ import annotations

from typing import Any, Callable

from services.api.app.chapter_translation_pipeline import (
    FLASH_PLANNING_MODEL,
    FLASH_PLANNING_PROMPT_VERSION,
    FLASH_QC_MODEL,
    FLASH_QC_PROMPT_VERSION,
    HY_MT2_MODEL_ID,
    HY_MT2_PROMPT_VERSION,
    ChapterTranslationPipeline,
    FlashPlanResult,
    FlashQcResult,
    HyMt2TranslationResult,
    expand_document_plan_segment_ranges,
    _sha256,
)


# Default deterministic translation table.  Mirrors the legacy
# FakeTranslationRunner dictionary in the batch tests so callers can use the
# fixture with no extra configuration for those sources.
DEFAULT_TRANSLATIONS: dict[str, str] = {
    "Participants must not receive SCS within 14 days.": "受试者在14天内不得接受SCS。",
    "The primary endpoint is assessed at Week 16.": "主要终点在第16周进行评估。",
    "Participants are eligible.": "受试者符合条件。",
    "The endpoint is assessed.": "对终点进行评估。",
    "The study uses a randomized parallel-group design.": "本研究采用随机平行组设计。",
    # Service tests use this source directly (single span).
    "Participants should complete the Week 16 assessment.": "受试者应完成第16周评估。",
}

# When a span is flagged as blocked, the Hy-MT2 fake emits this drifted text
# so the deterministic fidelity gate (numeric/negation drift) blocks it —
# matching the legacy FakeTranslationRunner behavior.
BLOCKED_TRANSLATION = "Participants receive SCS within 7 days."


class DeterministicFlashPlanner:
    """Records calls and returns a valid :class:`FlashPlanResult`.

    The Flash planner receives ``(source_text, context_dict)``.  Tests can
    inspect ``calls`` to confirm ``user_instruction`` and ``glossary_contract``
    were forwarded through the document context.

    Document-level planning requires every source span to be assigned to a
    chapter.  The default path consumes the process-local segment map and
    expands one complete segment range.  Provider-visible span IDs are not
    required.  A multi-chapter expanded override remains available for tests.
    """

    def __init__(self, model: str = FLASH_PLANNING_MODEL) -> None:
        self.model = model
        self.calls: list[tuple[str, dict[str, Any]]] = []
        # Optional override: list of chapter dicts with source_span_ids.
        self._chapter_override: list[dict[str, Any]] | None = None

    def set_chapter_assignments(
        self, chapters: list[dict[str, Any]]
    ) -> None:
        """Override the default single-chapter assignment for multi-chapter tests."""
        self._chapter_override = list(chapters)

    def __call__(self, source_text: str, context: dict[str, Any]) -> FlashPlanResult:
        # Defensive copy so later mutations do not rewrite history.
        self.calls.append((source_text, dict(context)))
        segments = tuple(context.get("_planner_segments") or ())
        if self._chapter_override is not None:
            chapters = list(self._chapter_override)
        elif segments:
            chapters = list(
                expand_document_plan_segment_ranges(
                    (
                        {
                            "id": "ch1",
                            "title": "Background",
                            "ich_m11_anchor": segments[0].ich_m11_anchor,
                            "start_segment_ordinal": 1,
                            "end_segment_ordinal": len(segments),
                        },
                    ),
                    segments,
                )
            )
        else:
            chapters = [{"id": "ch1", "title": "Background"}]
        plan_payload = {
            "chapters": chapters,
            "role": "protocol",
        }
        output_hash = _sha256(
            __import__("json").dumps(
                plan_payload, ensure_ascii=False, sort_keys=True
            )
        )
        return FlashPlanResult(
            # Must be a tuple of chapter dicts, not a 1-tuple wrapping a list.
            chapters=tuple(chapters),
            document_role=plan_payload["role"],
            plan_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            plan_model=self.model,
            plan_input_hash=_sha256(source_text),
            plan_output_hash=output_hash,
        )


class DeterministicHyMt2Translator:
    """Records calls (including glossary) and returns a valid Hy-MT2 result.

    The translator receives ``(source_text, glossary, chapter_id, chunk_id)``
    where ``glossary`` is the rendered contract string.  ``calls`` keeps the
    full tuple so tests can assert that the glossary contract reached the
    body translator.

    Translation lookup order:
      1. explicit override via ``translate_override(chunk_id) -> text``
      2. ``blocked_spans`` -> :data:`BLOCKED_TRANSLATION`
      3. ``translations[source_text]`` (falls back to source text)
      4. ``failures_remaining[chunk_id] > 0`` -> raise ``RuntimeError``
         (decremented per attempt) to simulate a transient provider failure.
    """

    def __init__(
        self,
        *,
        translations: dict[str, str] | None = None,
        blocked_spans: set[str] | None = None,
        failures_remaining: dict[str, int] | None = None,
        failure_message: str = "simulated fake AI failure",
        model: str = HY_MT2_MODEL_ID,
    ) -> None:
        self.model = model
        self.translations = dict(translations) if translations else dict(DEFAULT_TRANSLATIONS)
        self.blocked_spans: set[str] = set(blocked_spans or ())
        self.failures_remaining: dict[str, int] = dict(failures_remaining or {})
        self.failure_message = failure_message
        # Optional live source for the failure message — when set, the
        # translator reads the current message from this zero-arg callable
        # instead of the snapshot ``failure_message`` attribute.  This lets a
        # test reassign ``runner.failure_message`` and have the translator
        # see the new value on the next call.
        self.failure_message_fn: Callable[[], str] | None = None
        self.calls: list[tuple[str, str, str, str]] = []
        # chunk_id (span_id) list in call order — mirrors the legacy
        # FakeTranslationRunner.calls list used by batch assertions.
        self.span_calls: list[str] = []
        self._translate_override: Callable[[str], str | None] | None = None

    def set_translate_override(self, fn: Callable[[str], str | None]) -> None:
        """Override the translation for a given chunk_id (span_id).

        The override may return the translated text, or ``None`` to fall
        through to the default lookup (blocked_spans / translations table).
        """
        self._translate_override = fn

    def _lookup_translation(self, source_text: str) -> str:
        """Translate source_text, including multi-span merged chunks.

        V11: when source_text is unit-delimited (contains
        ``[[CMS_SEG_NNNN]]`` markers), translate each unit's inner text and
        emit unit-delimited output so the alignment contract passes.  Falls
        back to the legacy whole-text lookup when no markers are present.
        """
        import re as _re

        # V11 unit-delimited path.  Match raw ordinal strings as emitted.
        src_markers = list(
            _re.finditer(r"\[\[CMS_SEG_(\d{1,4})\]\]", source_text)
        )
        if src_markers:
            blocks = []
            for m in src_markers:
                raw_ordinal = m.group(1)
                ordinal = int(raw_ordinal)
                # Extract inner text using the raw ordinal string.
                inner_re = _re.compile(
                    rf"\[\[CMS_SEG_{_re.escape(raw_ordinal)}\]\]\s*(.*?)\s*\[\[/CMS_SEG_{_re.escape(raw_ordinal)}\]\]",
                    _re.DOTALL,
                )
                inner_match = inner_re.search(source_text)
                inner_text = inner_match.group(1) if inner_match else ""
                translated_inner = self._lookup_plain(inner_text)
                blocks.append(
                    f"[[CMS_SEG_{ordinal:04d}]]\n"
                    f"{translated_inner}\n"
                    f"[[/CMS_SEG_{ordinal:04d}]]"
                )
            return "\n\n".join(blocks)
        return self._lookup_plain(source_text)

    def _lookup_plain(self, source_text: str) -> str:
        """Translate a plain (non-unit-delimited) source text."""
        if source_text in self.translations:
            return self.translations[source_text]
        parts = source_text.split("\n\n")
        if len(parts) > 1 and all(part in self.translations for part in parts):
            return "\n\n".join(self.translations[part] for part in parts)
        return self.translations.get(source_text, source_text)

    def __call__(
        self,
        source_text: str,
        glossary: str,
        chapter_id: str,
        chunk_id: str,
        read_only_context: str = "",
        correction_note: str = "",
    ) -> HyMt2TranslationResult:
        # Record the call BEFORE the failure short-circuit so retry counters
        # and call lists reflect every attempt (matches the legacy runner,
        # which appended to ``calls`` before raising).
        # ``read_only_context`` and ``correction_note`` are recorded but
        # never mixed into the lookup key or output — output must correspond
        # only to ``source_text``.
        self.calls.append(
            (source_text, glossary, chapter_id, chunk_id, read_only_context, correction_note)
        )
        self.span_calls.append(chunk_id)
        failure_key = (
            chunk_id
            if chunk_id in self.failures_remaining
            else "*" if "*" in self.failures_remaining else chunk_id
        )
        remaining = self.failures_remaining.get(failure_key, 0)
        if remaining > 0:
            self.failures_remaining[failure_key] = remaining - 1
            message = (
                self.failure_message_fn()
                if self.failure_message_fn is not None
                else self.failure_message
            )
            raise RuntimeError(message)
        if self._translate_override is not None:
            override_result = self._translate_override(chunk_id)
            if override_result is not None:
                translated = override_result
            elif chunk_id in self.blocked_spans:
                translated = BLOCKED_TRANSLATION
            else:
                translated = self._lookup_translation(source_text)
        elif chunk_id in self.blocked_spans:
            translated = BLOCKED_TRANSLATION
        else:
            translated = self._lookup_translation(source_text)
        # Never echo read-only context into the translated output.
        return HyMt2TranslationResult(
            chapter_id=chapter_id,
            chunk_id=chunk_id,
            translated_text=translated,
            translated_text_sha256=_sha256(translated),
            model=self.model,
            prompt_version=HY_MT2_PROMPT_VERSION,
            input_hash=_sha256(source_text),
            output_hash=_sha256(translated),
        )


class DeterministicFlashQc:
    """Records calls and returns a passing :class:`FlashQcResult`.

    V11: when ``translated_text`` is an aligned marked envelope (per-unit
    SOURCE + DRAFT_ZH inside ``[[CMS_SEG_NNNN]]`` markers), the fake emits
    each unit's DRAFT_ZH content wrapped in the same markers — simulating a
    Flash integration that preserves markers exactly.  The pipeline then
    validates and strips markers, so the final persisted ``translated_text``
    is the plain Chinese candidate that tests assert on.  Legacy plain-text
    input passes through unchanged.
    """

    def __init__(
        self,
        model: str = FLASH_QC_MODEL,
        *,
        passed: bool = True,
        failure_codes: tuple[str, ...] = (),
    ) -> None:
        self.model = model
        self.passed = passed
        self.failure_codes = failure_codes
        self.calls: list[tuple[str, str, str]] = []

    def __call__(
        self, translated_text: str, source_text: str, correction_note: str = ""
    ) -> FlashQcResult:
        self.calls.append((translated_text, source_text, correction_note))
        from services.api.app.chapter_translation_pipeline import (
            contains_unit_markers,
            extract_draft_map_from_envelope,
        )

        if contains_unit_markers(translated_text):
            draft_map = extract_draft_map_from_envelope(translated_text)
            if draft_map:
                marked = "\n\n".join(
                    f"[[CMS_SEG_{ordinal:04d}]]\n{draft}\n[[/CMS_SEG_{ordinal:04d}]]"
                    for ordinal, draft in sorted(draft_map.items())
                )
            else:
                marked = translated_text
            integrated = marked if self.passed else ""
        else:
            integrated = translated_text if self.passed else ""
        return FlashQcResult(
            passed=self.passed,
            failure_codes=self.failure_codes,
            qc_prompt_version=FLASH_QC_PROMPT_VERSION,
            qc_model=self.model,
            qc_input_hash=_sha256(translated_text + source_text),
            qc_output_hash=_sha256(integrated),
            integrated_text=integrated,
            integrated_text_sha256=_sha256(integrated),
            notes="deterministic fake qc integration",
        )


def build_deterministic_pipeline(
    *,
    translations: dict[str, str] | None = None,
    blocked_spans: set[str] | None = None,
    failures_remaining: dict[str, int] | None = None,
    failure_message: str = "simulated fake AI failure",
) -> tuple[
    ChapterTranslationPipeline,
    DeterministicFlashPlanner,
    DeterministicHyMt2Translator,
    DeterministicFlashQc,
]:
    """Build a :class:`ChapterTranslationPipeline` with deterministic fakes.

    Returns the pipeline plus the three fake callables so tests can inspect
    ``calls`` and override behavior.  The OCR runner is a no-op because the
    writing-reference service never invokes OCR (spans carry extracted text).
    """
    planner = DeterministicFlashPlanner()
    translator = DeterministicHyMt2Translator(
        translations=translations,
        blocked_spans=blocked_spans,
        failures_remaining=failures_remaining,
        failure_message=failure_message,
    )
    qc = DeterministicFlashQc()
    pipeline = ChapterTranslationPipeline(
        ocr_runner=lambda *_args, **_kwargs: "",
        flash_planner=planner,
        hy_mt2_translator=translator,
        flash_qc_runner=qc,
    )
    return pipeline, planner, translator, qc


def wire_pipeline_calls_to_runner(
    runner: Any, translator: DeterministicHyMt2Translator
) -> None:
    """Expose ``translator.span_calls`` as ``runner.calls`` for legacy asserts.

    Batch tests previously asserted on ``runner.calls`` (a list of span_ids
    consumed by the legacy FakeTranslationRunner).  This helper keeps those
    assertions working by reflecting the deterministic translator's span call
    list onto the runner's ``calls`` attribute via a property.
    """

    class _CallProxy:
        def __init__(self, src: list[str]) -> None:
            self._src = src

        # Behave like a list: iteration, len, index, count, equality.
        def __iter__(self):
            return iter(self._src)

        def __len__(self) -> int:
            return len(self._src)

        def __getitem__(self, index):
            return self._src[index]

        def __contains__(self, item) -> bool:
            return item in self._src

        def __eq__(self, other) -> bool:
            return list(self._src) == list(other)

        def __repr__(self) -> str:
            return repr(self._src)

        def count(self, value) -> int:
            return self._src.count(value)

        def append(self, value) -> None:  # pragma: no cover - parity only
            self._src.append(value)

    runner.calls = _CallProxy(translator.span_calls)
