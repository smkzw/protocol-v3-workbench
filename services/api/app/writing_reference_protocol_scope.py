from __future__ import annotations

import re
from typing import Any


_SAP_SECTION_BOUNDARY_RE = re.compile(
    r"(?:^|[\r\n])\s*(?:#{1,6}\s*)?"
    r"(?:(?:appendix|附录)\s+[A-Z0-9.\-]+\s*[:：\-–—]?\s*)?"
    r"(?:statistical\s+analysis\s+plan|统计分析计划|统计分析方案)"
    r"(?:\s|$|[:：\-–—])",
    flags=re.IGNORECASE,
)

_PROTOCOL_CONTENT_SIGNALS = (
    re.compile(r"\bstudy\s+protocol\b", flags=re.IGNORECASE),
    re.compile(r"\bclinical\s+trial\s+protocol\b", flags=re.IGNORECASE),
    re.compile(r"\bprotocol\s+signature\s+page\b", flags=re.IGNORECASE),
    re.compile(r"\bprotocol\s+version\b", flags=re.IGNORECASE),
    re.compile(r"(?:临床试验方案|临床研究方案|方案签字页)"),
)


def _has_strong_protocol_structure(spans: list[Any]) -> bool:
    sample = "\n".join(
        "\n".join(
            (
                str(getattr(span, "section_heading", "") or ""),
                str(getattr(span, "source_text", "") or "")[:1200],
            )
        )
        for span in spans[:120]
    )
    matched_signal_count = sum(bool(pattern.search(sample)) for pattern in _PROTOCOL_CONTENT_SIGNALS)
    return matched_signal_count >= 2


def protocol_corpus_span_scope(
    artifact: Any,
    spans: list[Any],
) -> tuple[set[str], dict[str, str]]:
    """Return the source spans that may enter the competitor Protocol corpus."""

    document_type = str(getattr(artifact, "document_type", "") or "").lower()
    ordered = sorted(
        list(spans or []),
        key=lambda span: (
            int(getattr(span, "physical_page", 0) or 0),
            int(getattr(span, "block_index", 0) or 0),
            str(getattr(span, "span_id", "") or ""),
        ),
    )
    if document_type == "protocol":
        return {str(span.span_id) for span in ordered}, {}
    if document_type == "sap":
        return set(), {
            str(span.span_id): "standalone_sap_not_corpus_input"
            for span in ordered
        }
    if document_type != "protocol_sap":
        return set(), {
            str(span.span_id): "unsupported_document_type"
            for span in ordered
        }

    sap_boundary = next(
        (
            index
            for index, span in enumerate(ordered)
            if _SAP_SECTION_BOUNDARY_RE.search(
                "\n".join(
                    (
                        str(getattr(span, "section_heading", "") or ""),
                        str(getattr(span, "source_text", "") or "")[:800],
                    )
                )
            )
        ),
        None,
    )
    if sap_boundary is None or sap_boundary <= 0:
        if sap_boundary is None and _has_strong_protocol_structure(ordered):
            # ClinicalTrials.gov occasionally labels a Protocol file as
            # Protocol+SAP based on its upload slot/filename even though no
            # standalone SAP is appended. Content structure governs corpus
            # admission; source metadata remains available for provenance.
            return {str(span.span_id) for span in ordered}, {}
        return set(), {
            str(span.span_id): "combined_protocol_boundary_unresolved"
            for span in ordered
        }
    return (
        {str(span.span_id) for span in ordered[:sap_boundary]},
        {
            str(span.span_id): "sap_section_excluded_from_protocol_corpus"
            for span in ordered[sap_boundary:]
        },
    )
