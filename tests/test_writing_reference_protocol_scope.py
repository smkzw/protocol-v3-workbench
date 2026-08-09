from types import SimpleNamespace

from services.api.app.writing_reference_protocol_scope import (
    protocol_corpus_span_scope,
)


def _span(span_id: str, page: int, text: str, heading: str = ""):
    return SimpleNamespace(
        span_id=span_id,
        physical_page=page,
        block_index=0,
        source_text=text,
        section_heading=heading,
    )


def test_protocol_keeps_all_spans() -> None:
    spans = [_span("p1", 1, "Background"), _span("p2", 2, "Objectives")]
    included, excluded = protocol_corpus_span_scope(
        SimpleNamespace(document_type="protocol"),
        spans,
    )
    assert included == {"p1", "p2"}
    assert excluded == {}


def test_standalone_sap_is_excluded() -> None:
    included, excluded = protocol_corpus_span_scope(
        SimpleNamespace(document_type="sap"),
        [_span("s1", 1, "Primary analysis")],
    )
    assert included == set()
    assert excluded == {"s1": "standalone_sap_not_corpus_input"}


def test_combined_file_stops_at_explicit_sap_boundary() -> None:
    spans = [
        _span("p1", 1, "Study background"),
        _span("p2", 2, "Study objectives"),
        _span("s1", 10, "Version 1.0", "STATISTICAL ANALYSIS PLAN"),
        _span("s2", 11, "Analysis population"),
    ]
    included, excluded = protocol_corpus_span_scope(
        SimpleNamespace(document_type="protocol_sap"),
        spans,
    )
    assert included == {"p1", "p2"}
    assert excluded == {
        "s1": "sap_section_excluded_from_protocol_corpus",
        "s2": "sap_section_excluded_from_protocol_corpus",
    }


def test_combined_file_without_reliable_boundary_fails_closed() -> None:
    spans = [_span("x1", 1, "Study text"), _span("x2", 2, "Analysis text")]
    included, excluded = protocol_corpus_span_scope(
        SimpleNamespace(document_type="protocol_sap"),
        spans,
    )
    assert included == set()
    assert set(excluded.values()) == {"combined_protocol_boundary_unresolved"}


def test_protocol_mislabeled_as_combined_keeps_all_protocol_spans() -> None:
    spans = [
        _span(
            "p1",
            1,
            "A randomized clinical study protocol",
        ),
        _span("p2", 2, "Protocol version 5.0"),
        _span("p3", 3, "PROTOCOL SIGNATURE PAGE"),
        _span("p4", 20, "10.3 Statistical analysis plan"),
        _span("p5", 30, "References"),
    ]
    included, excluded = protocol_corpus_span_scope(
        SimpleNamespace(document_type="protocol_sap"),
        spans,
    )
    assert included == {"p1", "p2", "p3", "p4", "p5"}
    assert excluded == {}


def test_markdown_sap_appendix_heading_is_a_real_boundary() -> None:
    spans = [
        _span("p1", 1, "Study Protocol"),
        _span("p2", 2, "Protocol version 1.0"),
        _span("s1", 50, "Version 1.0", "## Appendix 8 - Statistical Analysis Plan"),
        _span("s2", 51, "Analysis populations"),
    ]
    included, excluded = protocol_corpus_span_scope(
        SimpleNamespace(document_type="protocol_sap"),
        spans,
    )
    assert included == {"p1", "p2"}
    assert set(excluded.values()) == {"sap_section_excluded_from_protocol_corpus"}
