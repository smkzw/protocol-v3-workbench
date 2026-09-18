"""Terminology is a scoped text check, not scientific or Word acceptance."""
def test_authored_text_suggests_preferred_term_at_each_actual_location():
    from services.api.app.protocol_workflow.terminology.library import TextUnit, scan_text_units
    units = [TextUnit(text='受试者接受评估。', locator=location, role=role)
             for role, location in [('body', 'b1'), ('table_cell', 't1:r0:c1'), ('header', 'h1'), ('footer', 'f1')]]
    findings = scan_text_units(units)
    assert len(findings) == 4
    assert all(f.code == 'preferred_participant_term' and f.severity == 'warning' for f in findings)
    assert [f.location for f in findings] == ['b1:chars:0-3', 't1:r0:c1:chars:0-3', 'h1:chars:0-3', 'f1:chars:0-3']


def test_quoted_titles_keep_original_terms_but_need_source_locator():
    from services.api.app.protocol_workflow.terminology.library import TextUnit, scan_text_units
    assert scan_text_units([TextUnit(text='受试者保护指南', locator='ref1', role='reference_title', source_locator='source.docx:para:9')]) == ()
    assert {f.code for f in scan_text_units([TextUnit(text='受试者保护指南', locator='ref1', role='reference_title')])} == {'quote_source_missing'}


def test_signature_is_not_a_license_for_draft_text_and_template_notes_cannot_leak():
    from services.api.app.protocol_workflow.terminology.library import TextUnit, scan_text_units
    assert scan_text_units([TextUnit(text='', locator='sig1', role='signature_control')]) == ()
    findings = scan_text_units([TextUnit(text='样本量待确认后写入。', locator='sig1', role='signature_control'),
                               TextUnit(text='请在此填写研究目的。', locator='note1', role='template_instruction')])
    assert {f.code for f in findings} == {'unresolved_draft_marker', 'template_instruction_leak'}


def test_format_warning_never_rewrites_quantities_or_codes():
    from services.api.app.protocol_workflow.terminology.library import TextUnit, scan_text_units
    text = '方案ABC-2026-01，版本1.2，2026年；剂量10ｍｇ，比例5％，另一量5μg。'
    findings = scan_text_units([TextUnit(text=text, locator='b1')])
    assert {f.code for f in findings} == {'full_width_unit', 'full_width_percent'}
    assert all(f.severity == 'warning' for f in findings)
    assert len(findings) == 2


def test_abbreviation_inventory_uses_observed_words_not_all_declared_entries():
    from services.api.app.protocol_workflow.terminology.library import TextUnit, abbreviation_inventory
    result = abbreviation_inventory(
        [TextUnit(text='记录AE和SAE，药物名XAE不是AE。', locator='b1'),
         TextUnit(text='SAE报告', locator='t1', role='table_cell')],
        candidates=['AE', 'SAE', 'ITT'], definitions={'AE': '不良事件', 'ITT': '意向性治疗'},
    )
    assert result['used'] == {'AE': ['b1'], 'SAE': ['b1', 't1']}
    assert result['missing_definitions'] == ['SAE']
    assert result['unused_definitions'] == ['ITT']
    assert result['full_form_review'] == 'not_performed'


def test_rules_do_not_claim_text_scan_proves_upright_font_or_medical_expansions():
    from services.api.app.protocol_workflow.terminology.library import load_library
    library = load_library()
    assert library['rule_status']['dose_unit_upright'] == 'requires_word_style_check'
    assert library['rule_status']['abbreviation_full_form'] == 'requires_semantic_review'
