"""Assemble the current authored template without reading historical run files.

Contracts remain in their authored files. This read-only composition produces
the existing registry shape and uses its existing source-bound catalog loaders.
It does not certify content, medical quality, or Word output.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
from .applicability import ApplicabilityRuleCatalog, load_applicability_rules
from .chapters import (
    ChapterRegistryDocument, ChapterSkillManifest, _expected_roles_from_template,
    load_chapter_registry,
)
from .fact_bindings import FactBindingCatalog, load_fact_catalog


@dataclass(frozen=True)
class CurrentTemplate:
    registry: ChapterRegistryDocument
    fact_catalog: FactBindingCatalog
    rules_catalog: ApplicabilityRuleCatalog


def load_current_template(root: Path) -> CurrentTemplate:
    root = Path(root)
    template = json.loads((root / "template.json").read_text())
    tree = json.loads((root / "node_tree.json").read_text())
    roles, _ = _expected_roles_from_template(tree)
    roles["v2_front_block"] = "cover"
    bindings = FactBindingCatalog.model_validate_json((root / "fact_bindings.json").read_text())
    rules = ApplicabilityRuleCatalog.model_validate_json((root / "applicability_rules.json").read_text())
    chapters, contracts, claims = [], [], set()
    for path in sorted((root / "chapter_contracts").glob("*.json")):
        contract = ChapterContractV2.model_validate_json(path.read_text())
        if path.stem != contract.semantic_node_id:
            raise ValueError("chapter file name and node identity differ")
        skill = ChapterSkillManifest.model_validate_json(
            (root / "chapter_skills" / path.name).read_text()
        )
        contracts.append(contract)
        content = contract.substantive_content
        claims.update(item.claim_type for item in content.claim_requirements)
        for rule in contract.conditional_applicability_rules:
            claims.update(rule.required_when_active_claim_types)
        for requirement in content.evidence_source_requirements:
            claims.update(requirement.admission_claim_types)
        chapters.append({
            "node_id": contract.semantic_node_id,
            "coverage_role": roles[contract.semantic_node_id],
            "contract": contract.model_dump(mode="json"),
            "skills": [skill.model_dump(mode="json")],
        })
    for rule in rules.rules:
        claims.update(rule.conditional_claim_types)
        claims.update(item.claim_type for item in rule.inactive_claim_requirements)
        for requirement in (*rule.active_evidence_requirements, *rule.inactive_evidence_requirements):
            claims.update(requirement.admission_claim_types)
    registry = load_chapter_registry({
        "schema_version": "protocol-v3-chapter-registry.v1",
        "generated_for": "current-authored-template",
        "authority": "Current authored contracts and source-bound catalogs; structure only.",
        "template_id": template["template_id"],
        "template_sha256": template["source"]["sha256"],
        "fact_vocabulary": sorted(binding.fact_path for binding in bindings.bindings),
        "claim_vocabulary": sorted(claims),
        "chapters": chapters,
        "fixtures": [],
    })
    return CurrentTemplate(
        registry=registry,
        fact_catalog=load_fact_catalog(root / "fact_bindings.json", registry),
        rules_catalog=load_applicability_rules(root / "applicability_rules.json", contracts),
    )


def default_template_root() -> Path:
    """Locate the current authored template from this file's repo anchor."""
    return (
        Path(__file__).resolve().parents[5]
        / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2"
    )


def applicability_rules_digest(rules) -> str:
    """Deterministic identity of one applicability rule set.

    Built exactly like the impact-plan digest over the sorted rule
    declarations, so a persisted plan and the adopted template identity carry
    the same verifiable rule-set binding.
    """
    payload = {
        "rules": [
            rule.model_dump(mode="json")
            for rule in sorted(rules, key=lambda rule: rule.rule_id)
        ]
    }
    blob = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def template_identity(template: CurrentTemplate) -> dict[str, Any]:
    """Source-bound identity of one loaded current template.

    Every value is computed from the source-bound loaded catalogs; nothing is
    accepted from the caller.  ``registry_sha256`` mirrors the dependency
    graph's registry hash so persisted impact plans bind the same assembly.
    """
    registry = template.registry
    return {
        "template_id": registry.template_id,
        "template_sha256": registry.template_sha256,
        "registry_sha256": hashlib.sha256(
            registry.model_dump_json().encode("utf-8")
        ).hexdigest(),
        "registry_binding_sha256": template.fact_catalog.registry_binding_sha256,
        "applicability_rules_sha256": applicability_rules_digest(
            template.rules_catalog.rules
        ),
        "fact_binding_count": len(template.fact_catalog.bindings),
        "applicability_rule_count": len(template.rules_catalog.rules),
    }
