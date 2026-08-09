from __future__ import annotations

from hashlib import sha256
import json
from typing import Iterable

from packages.contracts.workbench_contracts.models import (
    InterventionRulesIpActionKind,
    InterventionRulesIpAdjustmentPolicy,
    InterventionRulesLinkAction,
    InterventionRulesNonIpPolicy,
    InterventionRulesNonIpRuleClass,
    MedicalWritingInterventionCrossObjectLink,
    MedicalWritingInterventionIpActionRule,
    MedicalWritingInterventionNonIpTreatmentRule,
    MedicalWritingInterventionRules,
)


PANEL_BY_SECTION = {
    "6.4": "ip_actions",
    "6.9": "non_ip_rules",
    "6.10": "cm_rules",
}

_IP_ACTION_LABELS = {
    InterventionRulesIpActionKind.PLANNED_ON_OFF: "计划性暂停或恢复",
    InterventionRulesIpActionKind.TEMPORARY_INTERRUPTION: "暂时中断",
    InterventionRulesIpActionKind.RESUME: "恢复给药",
    InterventionRulesIpActionKind.PERMANENT_DISCONTINUATION: "永久停药",
    InterventionRulesIpActionKind.DISCONTINUATION_TAPER: "停药前递减",
    InterventionRulesIpActionKind.POST_DISCONTINUATION_FOLLOW_UP: "停药后随访",
    InterventionRulesIpActionKind.OTHER: "其他试验用药品处置",
}

_NON_IP_POLICY_LABELS = {
    InterventionRulesNonIpPolicy.ALLOWED: "允许使用",
    InterventionRulesNonIpPolicy.ALLOWED_IF_STABLE: "稳定剂量下允许使用",
    InterventionRulesNonIpPolicy.ALLOWED_WITH_APPROVAL: "经批准后允许使用",
    InterventionRulesNonIpPolicy.ALLOWED_WITH_TIMING: "满足时间限制后允许使用",
    InterventionRulesNonIpPolicy.PROHIBITED: "禁止使用",
    InterventionRulesNonIpPolicy.RESCUE_POLICY: "补救治疗",
}

_LINK_ACTION_LABELS = {
    InterventionRulesLinkAction.HOLD: "暂停试验用药品",
    InterventionRulesLinkAction.STOP: "停止试验用药品",
    InterventionRulesLinkAction.NO_AUTO_IP_ACTION: "不自动触发试验用药品处置",
    InterventionRulesLinkAction.RESUME: "恢复试验用药品",
}


class InterventionRulesProjectionConflictError(ValueError):
    pass


def intervention_rules_sha256(rules: MedicalWritingInterventionRules) -> str:
    payload = rules.model_dump(mode="json")
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def render_intervention_rules_panel(
    rules: MedicalWritingInterventionRules,
    section_number: str,
) -> str:
    if section_number == "6.4":
        paragraphs = _render_ip_actions(rules)
    elif section_number == "6.9":
        paragraphs = _render_non_ip_rules(
            rules,
            {
                InterventionRulesNonIpRuleClass.BACKGROUND,
                InterventionRulesNonIpRuleClass.RESCUE,
                InterventionRulesNonIpRuleClass.OTHER_NON_INVESTIGATIONAL,
            },
        )
    elif section_number == "6.10":
        paragraphs = _render_non_ip_rules(
            rules,
            {
                InterventionRulesNonIpRuleClass.ALLOWED_CM,
                InterventionRulesNonIpRuleClass.PROHIBITED_CM,
            },
        )
    else:
        raise ValueError(f"unsupported intervention-rules section: {section_number}")
    if not paragraphs:
        raise ValueError(
            f"intervention rules contain no projectable content for section {section_number}"
        )
    return "\n".join(paragraphs)


def build_intervention_rules_projection_block(
    *,
    rules: MedicalWritingInterventionRules,
    section_number: str,
    journey_id: str,
    journey_revision: int,
    body_order: int,
) -> dict:
    panel = PANEL_BY_SECTION.get(section_number)
    if panel is None:
        raise ValueError(f"unsupported intervention-rules section: {section_number}")
    rules_hash = intervention_rules_sha256(rules)
    identity = sha256(
        f"{journey_id}:{section_number}".encode("utf-8")
    ).hexdigest()[:20]
    text = render_intervention_rules_panel(rules, section_number)
    paragraphs = [
        {
            "type": "paragraph",
            "attrs": {"stylePreset": "body"},
            "content": [{"type": "text", "text": paragraph}],
        }
        for paragraph in text.split("\n")
    ]
    rich_text = paragraphs[0] if len(paragraphs) == 1 else {
        "type": "doc",
        "content": paragraphs,
    }
    projected_text_sha256 = sha256(text.encode("utf-8")).hexdigest()
    projected_content_sha256 = _projected_content_sha256(text, rich_text)
    return {
        "block_id": f"mwgenerated_intervention_{section_number.replace('.', '_')}_{identity}",
        "block_type": "paragraph",
        "text": text,
        "rich_text": rich_text,
        "body_order": body_order,
        "source_kind": "medical_writing_intervention_rules",
        "source_locator": (
            "generated:medical_writing_intervention_rules:"
            f"{journey_id}:r{journey_revision}:{section_number}"
        ),
        "editable": True,
        "projection_panel": panel,
        "target_section_number": section_number,
        "source_journey_revision": journey_revision,
        "source_intervention_rules_sha256": rules_hash,
        "projected_text_sha256": projected_text_sha256,
        "projected_content_sha256": projected_content_sha256,
        "render_contract_version": "medical_writing_intervention_rules_projection_v1",
    }


def merge_intervention_rules_projection_block(
    content_blocks: list[dict],
    projected_block: dict,
    *,
    overwrite_medical_edits: bool = False,
) -> tuple[list[dict], str]:
    target_section = projected_block["target_section_number"]
    matching = [
        (index, block)
        for index, block in enumerate(content_blocks)
        if block.get("source_kind") == "medical_writing_intervention_rules"
        and block.get("target_section_number") == target_section
    ]
    if len(matching) > 1:
        raise InterventionRulesProjectionConflictError(
            f"multiple intervention-rules projection blocks exist for section {target_section}"
        )
    merged = [dict(block) for block in content_blocks]
    if not matching:
        merged.append(projected_block)
        return merged, "inserted"
    index, existing = matching[0]
    expected_content_hash = str(existing.get("projected_content_sha256", ""))
    actual_content_hash = _projected_content_sha256(
        str(existing.get("text", "")),
        existing.get("rich_text"),
    )
    if expected_content_hash != actual_content_hash and not overwrite_medical_edits:
        raise InterventionRulesProjectionConflictError(
            "intervention-rules projection contains medical edits; explicit overwrite confirmation is required"
        )
    replacement = dict(projected_block)
    replacement["body_order"] = existing.get(
        "body_order", projected_block["body_order"]
    )
    merged[index] = replacement
    return merged, "updated"


def _projected_content_sha256(text: str, rich_text: object) -> str:
    return sha256(
        json.dumps(
            {"text": text, "rich_text": rich_text},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _render_ip_actions(rules: MedicalWritingInterventionRules) -> list[str]:
    paragraphs: list[str] = []
    if (
        rules.ip_adjustment_policy
        == InterventionRulesIpAdjustmentPolicy.NO_PLANNED_ADJUSTMENT
    ):
        paragraphs.append(rules.no_planned_adjustment_statement.rstrip("。") + "。")
    for rule in rules.ip_action_rules:
        paragraphs.append(_render_ip_action_rule(rule, rules.cross_object_links, rules))
    return paragraphs


def _render_ip_action_rule(
    rule: MedicalWritingInterventionIpActionRule,
    links: Iterable[MedicalWritingInterventionCrossObjectLink],
    rules: MedicalWritingInterventionRules,
) -> str:
    parts = [_IP_ACTION_LABELS[rule.action_kind]]
    _append(parts, "触发条件", rule.trigger)
    _append(parts, "严重程度或阈值", rule.severity_or_threshold)
    _append(parts, "确认要求", rule.confirmation_required)
    _append(parts, "试验用药品处置", rule.study_product_action)
    _append(parts, "复测或恢复条件", rule.retest_recovery)
    _append(parts, "等待期", rule.wait_period)
    _append(parts, "永久停药条件", rule.permanent_discontinuation_condition)
    if rule.taper_steps:
        _append(parts, "递减步骤", "；".join(rule.taper_steps))
    if rule.approvers:
        _append(parts, "批准或确认角色", "、".join(rule.approvers))
    if rule.exceptions:
        _append(parts, "例外", "；".join(rule.exceptions))
    linked_non_ip = {
        item.rule_id: item for item in rules.non_ip_treatment_rules
    }
    related_links = [
        link
        for link in links
        if link.target_rule_id == rule.rule_id
        or link.source_rule_id in rule.linked_non_ip_rule_ids
    ]
    for link in related_links:
        source = linked_non_ip.get(link.source_rule_id)
        source_name = (
            source.agent_or_category if source and source.agent_or_category else "关联的非试验用药或治疗"
        )
        relation = f"采用{source_name}时，{_LINK_ACTION_LABELS[link.action]}"
        if link.resume_condition:
            relation += f"；恢复条件：{link.resume_condition}"
        parts.append(relation)
    _append(parts, "补充说明", rule.notes)
    return "；".join(parts).rstrip("；。") + "。"


def _render_non_ip_rules(
    rules: MedicalWritingInterventionRules,
    included_classes: set[InterventionRulesNonIpRuleClass],
) -> list[str]:
    links_by_source: dict[str, list[MedicalWritingInterventionCrossObjectLink]] = {}
    for link in rules.cross_object_links:
        links_by_source.setdefault(link.source_rule_id, []).append(link)
    return [
        _render_non_ip_rule(rule, links_by_source.get(rule.rule_id, []))
        for rule in rules.non_ip_treatment_rules
        if rule.rule_class in included_classes
    ]


def _render_non_ip_rule(
    rule: MedicalWritingInterventionNonIpTreatmentRule,
    links: Iterable[MedicalWritingInterventionCrossObjectLink],
) -> str:
    subject = rule.agent_or_category or "未命名的非试验用药或治疗"
    parts = [f"{subject}：{_NON_IP_POLICY_LABELS[rule.policy]}"]
    _append(parts, "适用阶段", rule.phase_applicability)
    _append(parts, "收集或记录时间窗", rule.collection_window)
    _append(parts, "时间限制", "；".join(rule.timing_restrictions))
    _append(parts, "洗脱期或窗口", rule.washout_or_window)
    _append(parts, "非试验用药品剂量规定", rule.cm_dose_rule)
    if rule.exceptions:
        _append(parts, "例外", "；".join(rule.exceptions))
    for link in links:
        relation = f"关联试验用药品处置：{_LINK_ACTION_LABELS[link.action]}"
        if link.resume_condition:
            relation += f"；恢复条件：{link.resume_condition}"
        parts.append(relation)
    _append(parts, "补充说明", rule.notes)
    return "；".join(parts).rstrip("；。") + "。"


def _append(parts: list[str], label: str, value: str) -> None:
    normalized = value.strip()
    if normalized:
        parts.append(f"{label}：{normalized}")
