from __future__ import annotations

from copy import deepcopy

import pytest

from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository


SOURCE_BLOCK = {
    "block_id": "source_heading_6_4",
    "block_type": "heading",
    "text": "6.4 试验用药品剂量调整",
    "body_order": 10,
}


def _projected_block() -> dict:
    return {
        "block_id": "mwgenerated_intervention_6_4_4f9f5eaa2fd2",
        "block_type": "paragraph",
        "text": "本研究不计划进行常规剂量调整；发生方案规定的安全性事件时可暂停给药。",
        "body_order": 20,
        "source_kind": "medical_writing_intervention_rules",
        "source_locator": (
            "generated:medical_writing_intervention_rules:journey_demo:r4:6.4"
        ),
        "editable": True,
        "projection_panel": "ip_actions",
        "target_section_number": "6.4",
        "source_journey_revision": 4,
        "source_intervention_rules_sha256": "a" * 64,
        "projected_text_sha256": (
            "6293698f43c77bac703f5491f932ddc23c7c877f47b3078126fd3346fd0a4ee1"
        ),
        "projected_content_sha256": (
            "1bf996f8c1361b1426fde3e82116931e09f92d2496de2b58607eddf39af10c96"
        ),
        "render_contract_version": "medical_writing_intervention_rules_projection_v1",
    }


def test_server_authorized_projection_can_add_one_editable_paragraph():
    block = _projected_block()
    MedicalWritingRuntimeRepository._validate_working_copy_blocks(
        [SOURCE_BLOCK],
        [SOURCE_BLOCK, block],
        existing_blocks=[SOURCE_BLOCK],
        authorized_generated_blocks={block["block_id"]: block},
    )


def test_projected_paragraph_can_be_medically_edited_without_losing_lineage():
    existing = _projected_block()
    edited = deepcopy(existing)
    edited["text"] = "本研究不计划常规减量；符合暂停标准时暂停给药，并按方案规定恢复。"
    edited["rich_text"] = {
        "type": "paragraph",
        "attrs": {"stylePreset": "body"},
        "content": [{"type": "text", "text": edited["text"]}],
    }
    MedicalWritingRuntimeRepository._validate_working_copy_blocks(
        [SOURCE_BLOCK],
        [SOURCE_BLOCK, edited],
        existing_blocks=[SOURCE_BLOCK, existing],
    )


def test_client_cannot_forge_projection_or_change_its_lineage():
    forged = _projected_block()
    with pytest.raises(ValueError, match="server projection"):
        MedicalWritingRuntimeRepository._validate_working_copy_blocks(
            [SOURCE_BLOCK],
            [SOURCE_BLOCK, forged],
            existing_blocks=[SOURCE_BLOCK],
        )

    existing = _projected_block()
    tampered = deepcopy(existing)
    tampered["projection_panel"] = "cm_rules"
    with pytest.raises(ValueError, match="metadata|panel does not match"):
        MedicalWritingRuntimeRepository._validate_working_copy_blocks(
            [SOURCE_BLOCK],
            [SOURCE_BLOCK, tampered],
            existing_blocks=[SOURCE_BLOCK, existing],
        )


def test_client_cannot_silently_drop_or_break_projected_paragraph():
    existing = _projected_block()
    with pytest.raises(ValueError, match="preserve every server-projected"):
        MedicalWritingRuntimeRepository._validate_working_copy_blocks(
            [SOURCE_BLOCK],
            [SOURCE_BLOCK],
            existing_blocks=[SOURCE_BLOCK, existing],
        )

    invalid = deepcopy(existing)
    invalid["rich_text"] = {
        "type": "paragraph",
        "content": [{"type": "text", "text": "与纯文本不一致"}],
    }
    with pytest.raises(ValueError, match="must match block text"):
        MedicalWritingRuntimeRepository._validate_working_copy_blocks(
            [SOURCE_BLOCK],
            [SOURCE_BLOCK, invalid],
            existing_blocks=[SOURCE_BLOCK, existing],
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("block_id", "generated_6_4", "identity"),
        ("target_section_number", "6.10", "panel does not match"),
        ("source_intervention_rules_sha256", "short", "hash"),
        ("projected_text_sha256", "short", "hash"),
        ("projected_content_sha256", "short", "hash"),
    ],
)
def test_projection_contract_rejects_invalid_identity_section_or_hash(
    field: str,
    value: object,
    message: str,
):
    block = _projected_block()
    block[field] = value
    with pytest.raises(ValueError, match=message):
        MedicalWritingRuntimeRepository._validate_working_copy_blocks(
            [SOURCE_BLOCK],
            [SOURCE_BLOCK, block],
            existing_blocks=[SOURCE_BLOCK],
            authorized_generated_blocks={block["block_id"]: block},
        )
