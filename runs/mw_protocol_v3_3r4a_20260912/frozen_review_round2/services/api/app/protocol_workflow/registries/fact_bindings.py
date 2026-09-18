"""Project facts -> chapter inputs. No clinical inference or second fact store."""
from __future__ import annotations

import json
import math
import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.protocol_workflow.canonical.study_definition import study_revision_hash
from app.protocol_workflow.registries.chapters import (
    ChapterRegistryDocument, ChapterSkillInput, ChapterSkillOutput, _is_resolved_fact,
)
from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState, ChapterContractV2, NonEmptyText, PositiveRevision,
    Sha256, StableId, StudyDefinitionV3,
)


class FactBindingError(ValueError):
    def __init__(self, code: str, fact_paths: Iterable[str] = ()):
        self.code = code
        self.fact_paths = tuple(sorted(set(fact_paths)))
        super().__init__(f"{code}: {', '.join(self.fact_paths)}")


class FactBinding(BaseModel):
    """An explicit alias/type declaration, never an inferred scientific value."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_path: NonEmptyText
    canonical_path: NonEmptyText | None
    value_type: Literal["json", "boolean", "integer", "number", "string", "array", "object"]
    source_refs: tuple[NonEmptyText, ...] = Field(min_length=1)
    unit: str | None = None
    timing: str | None = None


class BoundChapterSkillInput(ChapterSkillInput):
    schema_version: Literal["protocol-v3-bound-chapter-input.v1"] = "protocol-v3-bound-chapter-input.v1"
    project_id: StableId
    study_definition_id: StableId
    study_revision: PositiveRevision
    study_sha256: Sha256
    chapter_contract_sha256: Sha256
    fact_bindings_sha256: Sha256
    source_format: Literal["native_json", "legacy_strings_v1"] = "native_json"


class FactBindingCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["protocol-v3-fact-bindings.v1"] = "protocol-v3-fact-bindings.v1"
    template_id: StableId
    template_sha256: Sha256
    registry_binding_sha256: Sha256
    bindings: tuple[FactBinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_paths(self):
        paths = [item.fact_path for item in self.bindings]
        if len(set(paths)) != len(paths):
            raise ValueError("fact binding paths must be unique")
        return self


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _registry_binding_hash(registry: ChapterRegistryDocument) -> str:
    payload = {
        "template_sha256": registry.template_sha256,
        "fact_vocabulary": sorted(registry.fact_vocabulary),
        "contracts": sorted(
            (entry.node_id, entry.contract.material_sha256()) for entry in registry.chapters
        ),
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def build_direct_fact_catalog(
    registry: ChapterRegistryDocument, *, declarations: Iterable[FactBinding] = (),
) -> FactBindingCatalog:
    """Record literal StudyDefinition.facts keys without inferring clinical types.

    Every key is linked to actual contract JSON locations. Generic JSON preserves
    canonical native types but deliberately cannot decode ambiguous legacy text.
    Pass the reviewed catalog's bindings when refreshing source locations, so
    approved aliases/types are preserved. Omitting declarations bootstraps a new
    catalog only; it must not replace an existing reviewed catalog.
    """
    references = {path: [] for path in registry.fact_vocabulary}

    def walk(value, locator):
        if isinstance(value, str) and value in references:
            references[value].append(locator)
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{locator}/{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{locator}/{index}")

    for entry in registry.chapters:
        walk(entry.contract.model_dump(mode="json"), f"chapter_contracts/{entry.node_id}.json#")
    unreferenced = [path for path, refs in references.items() if not refs]
    if unreferenced:
        raise FactBindingError("unreferenced_fact_vocabulary", unreferenced)
    declared = {}
    for binding in declarations:
        if binding.fact_path in declared:
            raise FactBindingError("duplicate_fact_binding", (binding.fact_path,))
        declared[binding.fact_path] = binding
    removed = set(declared) - set(references)
    if removed:
        raise FactBindingError("declared_fact_removed_from_registry", removed)
    refreshed = []
    for path, refs in sorted(references.items()):
        binding = declared.get(path)
        if binding is None:
            binding = FactBinding(fact_path=path, canonical_path=path,
                                  value_type="json", source_refs=tuple(sorted(set(refs))))
        else:
            # Declaration evidence remains available alongside current membership
            # locations; changes in clinical meaning still require source review.
            binding = binding.model_copy(update={
                "source_refs": binding.source_refs + tuple(sorted(set(refs) - set(binding.source_refs))),
            })
        refreshed.append(binding)
    return FactBindingCatalog(
        template_id=registry.template_id,
        template_sha256=registry.template_sha256,
        registry_binding_sha256=_registry_binding_hash(registry),
        bindings=tuple(refreshed),
    )


def load_fact_catalog(path: Path, registry: ChapterRegistryDocument) -> FactBindingCatalog:
    catalog = FactBindingCatalog.model_validate_json(Path(path).read_text(encoding="utf-8"))
    if (catalog.template_id != registry.template_id
        or catalog.template_sha256 != registry.template_sha256
        or catalog.registry_binding_sha256 != _registry_binding_hash(registry)):
        raise FactBindingError("fact_catalog_source_changed")
    paths = {binding.fact_path for binding in catalog.bindings}
    if paths != set(registry.fact_vocabulary):
        raise FactBindingError("fact_catalog_coverage_mismatch", paths ^ set(registry.fact_vocabulary))
    return catalog


def affected_chapter_fact_paths(bindings: Iterable[FactBinding], changed_canonical_paths: Iterable[str]) -> tuple[str, ...]:
    """Translate actual canonical changes into the contract vocabulary."""
    changed = set(changed_canonical_paths)
    return tuple(sorted({
        binding.fact_path for binding in bindings if binding.canonical_path in changed
    }))


def _typed_value(binding: FactBinding, value: JsonValue, source_format: str) -> JsonValue:
    kind = binding.value_type
    if source_format == "legacy_strings_v1" and isinstance(value, str) and kind != "string":
        if kind == "json":
            # A generic JSON slot does not tell us whether the old text meant a
            # boolean, number or prose. Never guess from its spelling.
            raise FactBindingError("legacy_fact_type_unresolved", (binding.fact_path,))
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            raise FactBindingError("legacy_fact_parse_failed", (binding.fact_path,)) from None
    matches = {
        "json": True,
        "boolean": type(value) is bool,
        "integer": type(value) is int,
        "number": type(value) in (int, float),
        "string": isinstance(value, str),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }[kind]
    if not matches or (isinstance(value, float) and not math.isfinite(value)):
        raise FactBindingError("fact_type_mismatch", (binding.fact_path,))
    try:
        _json(value)
    except (ValueError, TypeError):
        raise FactBindingError("fact_type_mismatch", (binding.fact_path,)) from None
    return value


def bind_chapter_input(
    study: StudyDefinitionV3,
    contract: ChapterContractV2,
    bindings: Iterable[FactBinding],
    *,
    source_format: Literal["native_json", "legacy_strings_v1"] = "native_json",
) -> BoundChapterSkillInput:
    """Read literal canonical dictionary keys; never split dotted paths.

    Required/conditional applicability remains the contract's responsibility.
    This boundary fails with exact paths when a required value cannot be read.
    Legacy conversion is opt-in and does not rewrite the original study.
    """
    if study.canonical_state not in (CanonicalState.CONFIRMED, CanonicalState.FROZEN):
        raise FactBindingError("study_not_confirmed")
    if source_format not in ("native_json", "legacy_strings_v1"):
        raise FactBindingError("unknown_fact_source_format")
    index = {}
    for binding in bindings:
        if binding.fact_path in index:
            raise FactBindingError("duplicate_fact_binding", (binding.fact_path,))
        index[binding.fact_path] = binding
    required = {
        item.fact_path for item in contract.substantive_content.fact_requirements
        if item.obligation.value == "required"
    }
    paths = {
        item.fact_path for item in contract.substantive_content.fact_requirements
        if item.obligation.value != "forbidden"
    }
    # Some trigger/conditional paths have no unconditional FactRequirement.
    # Carry available values now; 3R.4B decides which obligations activate.
    forbidden = {
        item.fact_path for item in contract.substantive_content.fact_requirements
        if item.obligation.value == "forbidden"
    }
    for rule in contract.conditional_applicability_rules:
        paths.update(rule.triggering_fact_paths)
        paths.update(rule.required_when_active_fact_paths)
    for item in contract.ctq_items:
        paths.update(item.linked_fact_paths)
    for item in contract.registry_consistency_obligations:
        paths.update(item.eligibility_fact_paths)
    paths.difference_update(forbidden)
    resolved, missing, unsupported = {}, [], []
    for path in sorted(paths):
        binding = index.get(path)
        if binding is None or binding.canonical_path is None:
            if path in required:
                unsupported.append(path)
            continue
        if binding.canonical_path not in study.facts:
            if path in required:
                missing.append(path)
            continue
        value = _typed_value(binding, study.facts[binding.canonical_path], source_format)
        if binding.canonical_path != path and path in study.facts:
            alias_value = _typed_value(binding, study.facts[path], source_format)
            if _json(value) != _json(alias_value):
                raise FactBindingError("fact_alias_conflict", (path, binding.canonical_path))
        if not _is_resolved_fact(value):
            if path in required:
                missing.append(path)
            continue
        resolved[path] = value
    if unsupported:
        raise FactBindingError("unsupported_required_fact", unsupported)
    if missing:
        raise FactBindingError("missing_required_fact", missing)
    if not resolved:
        raise FactBindingError("chapter_has_no_resolved_facts", paths)
    return BoundChapterSkillInput(
        chapter_contract_id=contract.chapter_contract_id,
        node_id=contract.semantic_node_id,
        template_id=contract.template_id,
        template_sha256=contract.template_sha256,
        word_rules=contract.word_rules,
        resolved_facts=resolved,
        project_id=study.project_id,
        study_definition_id=study.study_definition_id,
        study_revision=study.revision,
        study_sha256=study_revision_hash(study),
        chapter_contract_sha256=contract.material_sha256(),
        fact_bindings_sha256=hashlib.sha256(_json([
            index[path].model_dump(mode="json") for path in sorted(paths) if path in index
        ]).encode("utf-8")).hexdigest(),
        source_format=source_format,
    )


def validate_output_facts(
    bound: BoundChapterSkillInput,
    output: ChapterSkillOutput,
    current_study: StudyDefinitionV3,
    *,
    contract: ChapterContractV2,
    bindings: Iterable[FactBinding],
) -> None:
    """Validate against fresh canonical resolution, not writer self-report.

    This is fact equality/snapshot checking only; callers must also run
    chapter/evidence/applicability/medical checks before adoption.
    """
    if (bound.project_id != current_study.project_id
        or bound.study_definition_id != current_study.study_definition_id
        or bound.study_revision != current_study.revision
        or bound.study_sha256 != study_revision_hash(current_study)):
        raise FactBindingError("study_snapshot_stale")
    expected = bind_chapter_input(
        current_study, contract, bindings, source_format=bound.source_format,
    )
    if _json(bound.model_dump(mode="json")) != _json(expected.model_dump(mode="json")):
        raise FactBindingError("chapter_input_binding_mismatch")
    if output.chapter_contract_id != bound.chapter_contract_id or output.node_id != bound.node_id:
        raise FactBindingError("output_chapter_mismatch")
    conflicts = []
    for fact in output.facts:
        try:
            matches = (fact.fact_path in expected.resolved_facts
                       and _json(fact.value) == _json(expected.resolved_facts[fact.fact_path]))
        except (ValueError, TypeError):
            matches = False
        if not matches:
            conflicts.append(fact.fact_path)
    if conflicts:
        raise FactBindingError("output_fact_mismatch", conflicts)
