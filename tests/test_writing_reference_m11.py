from services.api.app.writing_reference_m11 import m11_anchor_from_ocr_page


def test_ocr_page_mapping_uses_heading_not_incidental_body_terms() -> None:
    anchor, heading = m11_anchor_from_ocr_page(
        "1.2 State of the art\n"
        "Long-term outcomes include safety observations and statistical comparisons."
    )

    assert anchor == "rationale"
    assert heading == "1.2 State of the art"


def test_ocr_page_mapping_supports_core_protocol_sections() -> None:
    cases = {
        "Study Population:\nAdults with COPD": "eligibility",
        "Identity of Study Medication\nDose details": "intervention",
        "2.1 General Study Design\nRandomized trial": "study_design",
        "3. Data Collection of the Trial\nSource records": "data_management",
        "5. Reference List\n1. Example": "references",
    }

    for text, expected in cases.items():
        assert m11_anchor_from_ocr_page(text)[0] == expected


def test_ocr_continuation_page_stays_unmapped_without_a_heading() -> None:
    anchor, heading = m11_anchor_from_ocr_page(
        "This continuation paragraph discusses safety and statistical analysis "
        "inside ordinary body prose without a section heading."
    )

    assert anchor == "unmapped"
    assert heading == ""
