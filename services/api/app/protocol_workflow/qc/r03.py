"""3R.5A R03 QC-table criteria checks and registry loader.

Two deterministic checks are implemented, on typed inputs only (the real
document projection and the product consumers -- generation model, native
Word export, UI -- are V1 wiring and are NOT claimed connected):

- ``qc.r03:version_four_point`` -- the protocol identity four-point
  (title / number / version / date) must agree across every current
  location; revision-history rows legally keep their old values and are
  never compared against the current version.  Empty or missing materials
  fail closed.
- ``qc.r03:internal_cross_reference`` -- textual citations must resolve
  against an explicit declared target-object list (not against "contains a
  number"); missing targets and empty materials fail closed.

Everything else in the R03 registry stays explicitly pending; pending checks
are surfaced through ``deferred_qc_obligations`` rather than being counted
as evaluated.  The registry loader re-validates source identity, atom
bindings, uniqueness and check references so a drifted or hand-broken
registry fails loudly instead of producing fake passes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict

from ..registries.chapters import CheckerFinding, FixtureCheckResult

ROOT = Path(__file__).resolve().parents[5]  # repo root (qc -> ... -> services)
REGISTRY_PATH = ROOT / "config/medical_writing/protocol_v3/qc/r03_criteria.json"
NODE_TREE_PATH = (
    ROOT / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2/node_tree.json"
)
APPLICABILITY_RULES_PATH = (
    ROOT
    / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2/applicability_rules.json"
)
EXPECTED_SOURCE_SHA256 = (
    "5a5affebd36979cb06e9de239accc163f954c186afcdf3668f23d054400519e9"
)

CHAPTER_CONTRACT_ID = "r03_qc_registry"
SUBJECT_ID = "r03_typed_input"

PENDING_L1_OBLIGATIONS = (
    "l1_abbreviation_closure",
    "l1_literature_bidirectional",
    "l1_numbers_units",
    "l1_registration_consistency",
)

REQUIRED_L1_IDS = (
    "l1_version_four_point",
    "l1_abbreviation_closure",
    "l1_literature_bidirectional",
    "l1_textual_cross_reference",
    "l1_numbers_units",
    "l1_registration_consistency",
)


class R03RegistryError(RuntimeError):
    """Raised when the committed registry fails loader validation."""


# ---------------------------------------------------------------------------
# Typed inputs
# ---------------------------------------------------------------------------


class R03VersionPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = ""
    protocol_number: str = ""
    version_number: str = ""
    version_date: str = ""


class R03VersionMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    current: R03VersionPoint
    current_locations: Mapping[str, R03VersionPoint]
    revision_history: tuple[R03VersionPoint, ...] = ()


class R03Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    target_id: str


class R03CitationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str
    kind: str
    description: str = ""


class R03CitationMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    citations: tuple[R03Citation, ...] = ()
    targets: tuple[R03CitationTarget, ...] = ()
    #: Explicit signal that the citation projection actually ran and this is
    #: the complete scope.  An empty material WITHOUT this flag is an absent
    #: projection and fails closed; a completed zero-citation scope passes
    #: without inventing targets.
    projection_completed: bool = False


# ---------------------------------------------------------------------------
# Deterministic checks (typed inputs, fail closed on empty materials)
# ---------------------------------------------------------------------------


def _result(
    findings: list[CheckerFinding],
    subject_id: str = SUBJECT_ID,
) -> FixtureCheckResult:
    return FixtureCheckResult(
        subject_id=subject_id,
        chapter_contract_id=CHAPTER_CONTRACT_ID,
        passed=not any(f.severity == "error" for f in findings),
        findings=tuple(findings),
        deferred_qc_obligations=PENDING_L1_OBLIGATIONS,
    )


def _finding(code: str, location: str, message: str) -> CheckerFinding:
    return CheckerFinding(
        code=code, severity="error", location=location, message=message
    )


def _is_blank(value: str) -> bool:
    return not str(value).strip()


def check_version_consistency(
    material: R03VersionMaterial | None, *, subject_id: str = SUBJECT_ID
) -> FixtureCheckResult:
    """Current four-point identity must agree across all current locations.

    Whitespace-only required identity fields count as missing (a blank form
    is not a passing identity).  Original field values are quoted verbatim in
    findings and never rewritten.  Revision-history rows are deliberately
    never compared: old versions with old dates are legal and stay untouched.
    """
    findings: list[CheckerFinding] = []
    if material is None:
        findings.append(
            _finding(
                "r03_material_missing",
                "material",
                "版本四点材料缺失：没有typed投影时不得给出通过结论。",
            )
        )
        return _result(findings, subject_id)
    if not material.current_locations:
        findings.append(
            _finding(
                "r03_material_missing",
                "material.current_locations",
                "没有任何当前位置投影，无法核对一致性；按失败关闭处理。",
            )
        )
    empty = [
        field
        for field in ("title", "protocol_number", "version_number", "version_date")
        if _is_blank(getattr(material.current, field))
    ]
    if empty:
        findings.append(
            _finding(
                "r03_version_field_empty",
                "current",
                f"当前版本四点字段缺失（含纯空白）：{', '.join(empty)}；"
                "空白表格不构成通过。",
            )
        )
    for name, observed in material.current_locations.items():
        for field in ("title", "protocol_number", "version_number", "version_date"):
            expected = getattr(material.current, field)
            actual = getattr(observed, field)
            if not _is_blank(expected) and actual != expected:
                findings.append(
                    _finding(
                        "r03_version_inconsistent",
                        f"current_locations[{name}].{field}",
                        f"当前位置{name}的{field}为{actual!r}，"
                        f"与当前版本{expected!r}不一致。",
                    )
                )
    return _result(findings, subject_id)


def check_internal_citations(
    material: R03CitationMaterial | None, *, subject_id: str = SUBJECT_ID
) -> FixtureCheckResult:
    """Textual citations must resolve against the declared target objects.

    The target list is the authority: a citation is resolved only when its
    target id exists in the declared objects.  Blank citation text, blank
    citation target ids, blank target ids and blank target kinds are
    rejected.  An empty material without the explicit ``projection_completed``
    signal is an absent projection and fails closed; ``projection_completed``
    with a legitimately empty citation scope passes without inventing
    targets.  Declaring completion never excuses blank fields or unresolved
    targets.  These are document-completeness checks, not security work.
    """
    findings: list[CheckerFinding] = []
    if material is None:
        findings.append(
            _finding(
                "r03_material_missing",
                "material",
                "引用检查材料缺失：没有typed投影时不得给出通过结论。",
            )
        )
        return _result(findings, subject_id)
    if not material.citations and not material.targets:
        if not material.projection_completed:
            findings.append(
                _finding(
                    "r03_material_missing",
                    "material",
                    "引用与目标对象均为空且未声明投影已完成：按未投影处理，"
                    "不得判为通过。",
                )
            )
            return _result(findings, subject_id)
        return _result(findings, subject_id)
    for index, target in enumerate(material.targets):
        if _is_blank(target.target_id):
            findings.append(
                _finding(
                    "r03_citation_target_blank",
                    f"targets[{index}].target_id",
                    "目标对象缺少target_id（身份字段为空/纯空白）。",
                )
            )
        if _is_blank(target.kind):
            findings.append(
                _finding(
                    "r03_citation_target_kind_blank",
                    f"targets[{index}].kind",
                    "目标对象缺少kind（类型字段为空/纯空白）。",
                )
            )
    for index, citation in enumerate(material.citations):
        if _is_blank(citation.text):
            findings.append(
                _finding(
                    "r03_citation_text_blank",
                    f"citations[{index}].text",
                    "文字引用缺少引用文本（显示字段为空/纯空白）。",
                )
            )
        if _is_blank(citation.target_id):
            findings.append(
                _finding(
                    "r03_citation_target_blank",
                    f"citations[{index}].target_id",
                    "文字引用缺少目标对象ID（身份字段为空/纯空白）。",
                )
            )
    target_ids = [target.target_id for target in material.targets
                  if not _is_blank(target.target_id)]
    known = set(target_ids)
    for index, target_id in enumerate(target_ids):
        if target_ids.count(target_id) > 1:
            findings.append(
                _finding(
                    "r03_citation_target_duplicate",
                    f"targets[{index}]",
                    f"目标对象{target_id!r}在清单中重复声明。",
                )
            )
    for index, citation in enumerate(material.citations):
        if _is_blank(citation.target_id):
            continue
        if citation.target_id not in known:
            findings.append(
                _finding(
                    "r03_citation_target_unresolved",
                    f"citations[{index}]",
                    f"文字引用「{citation.text}」的目标对象{citation.target_id!r}"
                    "不在明确目标清单中，无法解析。",
                )
            )
    return _result(findings, subject_id)


KNOWN_CHECKS: dict[str, Any] = {
    "qc.r03:version_four_point": check_version_consistency,
    "qc.r03:internal_cross_reference": check_internal_citations,
}


def signature_control_status(raw_text: str) -> dict[str, Any]:
    """Classify the R03 QC-table signature paragraph.

    The blank signature control is a legal empty control, never a draft
    placeholder and never a forged signature; actual signing evidence
    belongs to the V1 formal receipt flow.
    """
    if "填表人签字" in raw_text:
        return {
            "state": "blank_control",
            "is_draft_marker": False,
            "note": "签署控件保留空白；不生成签名或日期，不判为草稿占位符。",
        }
    return {
        "state": "signature_area_not_found",
        "is_draft_marker": False,
        "note": "输入文本不是R03签署区段落，本函数不做草稿判定。",
    }


# ---------------------------------------------------------------------------
# Registry loader (real reliability checks, fail loud)
# ---------------------------------------------------------------------------


class R03Criterion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    atom_id: str
    source_locator: str
    sub_key: str
    source_label: str
    raw_fragment: str
    normalized_check: str
    check_category: Literal["deterministic", "agent4", "human"]
    semantic_node_ids: tuple[str, ...]
    applicability: Mapping[str, Any]
    evidence_requirement: str
    implementation_status: Literal["implemented", "pending"]
    check_ref: str | None
    human_confirmation_ref: str | None
    flags: tuple[str, ...]
    note: str


class R03CriteriaDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    template_id: str
    status: str
    source_sha256: str
    denominator: Mapping[str, Any]
    criteria: tuple[R03Criterion, ...]
    l1_check_ids: tuple[str, ...]


def _norm(text: str) -> str:
    return "".join(text.split())


def _known_semantic_node_ids() -> set[str]:
    node_tree = json.loads(NODE_TREE_PATH.read_text(encoding="utf-8"))
    known = {
        node["id"]
        for tree in ("heading_style_tree", "outlined_tree")
        for node in (node_tree.get(tree, {}).get("nodes") or [])
    }
    if node_tree.get("front_block"):
        known.add("v2_front_block")
    return known


def _known_applicability_rule_ids() -> set[str]:
    rules = json.loads(APPLICABILITY_RULES_PATH.read_text(encoding="utf-8"))
    return {rule["rule_id"] for rule in rules.get("rules", [])}


def validate_r03_registry(data: Mapping[str, Any]) -> list[str]:
    """Return a list of concrete problems; empty list means the registry is
    internally consistent.  Graph/source counts only -- medical sufficiency
    is never judged here."""
    problems: list[str] = []
    sources = data.get("source") or []
    if not sources:
        problems.append("registry declares no source record")
        return problems
    observed_sha = sources[0].get("sha256")
    if observed_sha != EXPECTED_SOURCE_SHA256:
        problems.append(
            f"source hash mismatch: expected {EXPECTED_SOURCE_SHA256}, "
            f"observed {observed_sha!r}"
        )

    rows = data.get("source_rows") or []

    def _locator(row: Mapping[str, Any]) -> str:
        return f"table[{row['table_index']}]/row[{row['row_index']}]"

    row_texts = {
        _locator(row): " ".join(
            "".join(cell["paragraphs"]) for cell in row["cells"]
        )
        for row in rows
    }
    kinds = [row.get("row_kind") for row in rows]
    denominator = data.get("denominator") or {}
    expected_counts = {
        "physical_rows": len(rows),
        "identity_rows": kinds.count("identity"),
        "repeated_header_rows": kinds.count("header"),
        "source_content_rows": kinds.count("content"),
    }
    for key, expected in expected_counts.items():
        if denominator.get(key) != expected:
            problems.append(
                f"denominator mismatch for {key}: declared "
                f"{denominator.get(key)!r}, observed {expected}"
            )
    criteria = data.get("criteria") or []
    if denominator.get("atomic_obligations") != len(criteria):
        problems.append(
            f"denominator atomic_obligations is {denominator.get('atomic_obligations')!r} "
            f"but {len(criteria)} atoms are present"
        )

    seen_ids: set[str] = set()
    for atom in criteria:
        atom_id = atom.get("atom_id", "<missing>")
        if atom_id in seen_ids:
            problems.append(f"duplicate atom_id {atom_id!r}")
        seen_ids.add(atom_id)

    known_nodes = _known_semantic_node_ids()
    known_rules = _known_applicability_rule_ids()
    for atom in criteria:
        atom_id = atom.get("atom_id", "<missing>")
        locator = atom.get("source_locator", "")
        if locator.endswith("cell[1]"):
            fragments = data.get("header_embedded_fragments") or []
            haystacks = [f.get("raw_text", "") for f in fragments]
            if not any(
                _norm(atom.get("raw_fragment", "")) in _norm(text)
                for text in haystacks
            ):
                problems.append(
                    f"atom {atom_id} raw_fragment not found in header fragment"
                )
        else:
            if locator not in row_texts:
                problems.append(
                    f"atom {atom_id} references unknown source locator {locator!r}"
                )
            elif _norm(atom.get("raw_fragment", "")) not in _norm(
                row_texts[locator]
            ):
                problems.append(
                    f"atom {atom_id} raw_fragment not found in source row "
                    f"{locator}"
                )
        for node_id in atom.get("semantic_node_ids") or []:
            if node_id not in known_nodes:
                problems.append(
                    f"atom {atom_id} binds unknown semantic node {node_id!r}"
                )
        rule_ref = (atom.get("applicability") or {}).get("rule_ref")
        if rule_ref is not None and rule_ref not in known_rules:
            problems.append(
                f"atom {atom_id} references unknown applicability rule "
                f"{rule_ref!r}"
            )
        check_ref = atom.get("check_ref")
        if check_ref is not None and check_ref not in KNOWN_CHECKS:
            problems.append(
                f"atom {atom_id} references unknown check implementation "
                f"{check_ref!r}"
            )
        if atom.get("implementation_status") == "implemented" and not check_ref:
            problems.append(
                f"atom {atom_id} is implemented but binds no check_ref"
            )

    covered = {
        atom["source_locator"]
        for atom in criteria
        if not atom["source_locator"].endswith("cell[1]")
    }
    for row in rows:
        if row.get("row_kind") != "content":
            continue
        locator = _locator(row)
        if locator not in covered:
            problems.append(
                f"content row {locator} not covered by any atomic obligation"
            )

    fragments = data.get("header_embedded_fragments") or []
    if len(fragments) != 1 or fragments[0].get("source_locator") != (
        "table[5]/row[0]/cell[1]"
    ):
        problems.append(
            "header-embedded recruitment fragment missing or relocated"
        )

    signature = data.get("signature_area") or {}
    if "填表人签字" not in (signature.get("raw_text") or ""):
        problems.append("signature area missing from registry")

    l1_ids = {entry.get("id") for entry in data.get("l1_checks") or []}
    missing_l1 = [lid for lid in REQUIRED_L1_IDS if lid not in l1_ids]
    if missing_l1:
        problems.append(f"L1 registration incomplete: missing {missing_l1}")

    wired = data.get("wired_checks") or []
    wired_refs = {check.get("check_ref") for check in wired}
    if wired_refs != set(KNOWN_CHECKS):
        problems.append(
            f"wired_checks do not match implemented checks: {sorted(wired_refs)}"
        )
    for check in wired:
        function = KNOWN_CHECKS.get(check.get("check_ref"))
        if function is not None and check.get("function") not in (
            function.__name__,
        ):
            problems.append(
                f"wired check {check.get('check_ref')!r} points to function "
                f"{check.get('function')!r} which is not the implementation"
            )
    return problems


def load_r03_criteria(path: Path | str = REGISTRY_PATH) -> R03CriteriaDocument:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    problems = validate_r03_registry(data)
    if problems:
        raise R03RegistryError(
            "r03 criteria registry failed closed:\n- " + "\n- ".join(problems)
        )
    criteria = tuple(R03Criterion.model_validate(atom) for atom in data["criteria"])
    return R03CriteriaDocument(
        schema_version=data["schema_version"],
        template_id=data["template_id"],
        status=data["status"],
        source_sha256=data["source"][0]["sha256"],
        denominator=data["denominator"],
        criteria=criteria,
        l1_check_ids=tuple(entry["id"] for entry in data["l1_checks"]),
    )
