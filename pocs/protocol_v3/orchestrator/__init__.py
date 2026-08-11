"""Protocol v3 orchestrator PoC — shared immutable case contracts (Task 2.1).

Worker 01 of Task 2.1 defines the *closed immutable vocabulary* that the
three high-risk case graphs (eligibility, objective-estimand-endpoint,
sample-size) are built from, plus the validation that makes a case graph
fail closed:

* closed enums: :class:`CaseId`, :class:`GateKind`, :class:`OwnerRole`,
  :class:`NodeKind`, :class:`EdgeKind`, :class:`SideEffectKind`,
  :class:`InjectionKind`, :class:`FailurePolicy`;
* immutable models: :class:`SchemaDecl`, :class:`NodeContract`,
  :class:`Edge`, :class:`InjectionPoint`, :class:`CaseGraph`;
* a deterministic material SHA-256 bound to ``case_id``, ``project_id``,
  ``branch_id``, schema version and ``graph_version``; the models carry no
  timestamps, run ids, sessions or counters, so runtime/scheduler-private
  state cannot leak into the hash and equivalent construction hashes
  identically (nodes/edges/injections/schemas are canonicalized by sort);
* fail-closed validation at construction: duplicate/unknown nodes, unknown
  dependencies, cycles, invalid owner/Gate/schema, dangling or duplicate
  inputs, branch/project mismatch and mutable nested input are rejected;
* the five explicit injection kinds (kill-before, kill-after,
  duplicate-resume, concurrent-decision, old-graph-migration) are declared
  per case as :class:`InjectionPoint` records and are *never executed* here
  (no scheduler, no runtime).

PoC-only artifact under ``pocs/protocol_v3/orchestrator/``.  MUST NOT be
imported by product code — same rule as ``pocs/protocol_v3/storage``.  Only
stdlib + the already-pinned Pydantic are used; no product module is
imported.  Enum/model naming mirrors the accepted Phase 1 contracts
(``packages/contracts/workbench_contracts/protocol_v3.py``:
``GateKind`` D1/Q1, ``OwnerRole`` agent roles, ``SideEffectKind`` names,
``StableId``/``Sha256`` shapes, frozen ``extra="forbid"`` models and the
material-hash discipline) so later Task 2.2 adapter work maps 1:1.

Construction of a model raises ``pydantic.ValidationError`` (wrapping a
:class:`CaseContractError`); helpers called on an already-constructed graph
raise :class:`CaseContractError` directly.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import Enum
from typing import (
    Annotated,
    Any,
    ClassVar,
    Literal,
    Optional,
    Tuple,
)

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

__all__ = [
    "CASE_CONTRACT_SCHEMA_VERSION",
    "CASE_IDS",
    "INJECTION_KINDS",
    "StableId",
    "Sha256",
    "NonEmptyText",
    "AwareDateTime",
    "PositiveRevision",
    "CaseId",
    "GateKind",
    "OwnerRole",
    "NodeKind",
    "EdgeKind",
    "SideEffectKind",
    "InjectionKind",
    "FailurePolicy",
    "SchemaDecl",
    "NodeContract",
    "Edge",
    "InjectionPoint",
    "CaseGraph",
    "CaseContractError",
    "FrozenJsonDict",
    "FrozenJsonList",
    "freeze_input",
    "assert_deep_immutable",
    "assert_case_graph_binding",
    "canonical_json",
]

#: Schema version of this orchestrator case-contract vocabulary itself.  A
#: graph pins this plus a per-case ``graph_version``; both participate in the
#: material hash.
CASE_CONTRACT_SCHEMA_VERSION = "mw_protocol_v3_orchestrator_case_contract_v1"

#: The three Task 2.1 cases, in plan order.
CASE_IDS: Tuple[CaseId, ...]  # forward ref; assigned after CaseId definition


def _require_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an explicit timezone")
    return value


#: Same identity shapes as the accepted Phase 1 contracts so project/branch
#: and node ids are interchangeable with product ids.
StableId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=160,
        pattern=r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$",
    ),
]
Sha256 = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
AwareDateTime = Annotated[datetime, AfterValidator(_require_aware_datetime)]
PositiveRevision = Annotated[int, Field(ge=1)]


class CaseContractError(ValueError):
    """Typed, stable failure emitted by the PoC contract vocabulary.

    Mirrors ``pocs/protocol_v3/word_receipt/contract.py`` error style:
    ``code`` is a stable machine name, ``path`` locates the offending
    field inside the graph, ``message`` is human-readable.
    """

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")


# ---------------------------------------------------------------------------
# Closed enums
# ---------------------------------------------------------------------------


class CaseId(str, Enum):
    """Closed set of Task 2.1 PoC cases; values equal case module names."""

    ELIGIBILITY = "eligibility"
    OBJECTIVE_ESTIMAND_ENDPOINT = "objective_estimand_endpoint"
    SAMPLE_SIZE = "sample_size"


CASE_IDS = (CaseId.ELIGIBILITY, CaseId.OBJECTIVE_ESTIMAND_ENDPOINT, CaseId.SAMPLE_SIZE)


class GateKind(str, Enum):
    """Closed set of gates a case node can be subject to.

    D1 and Q1 keep the authoritative names of the accepted design
    (design-v1.2 §10.4/§13); ``user_decision`` is the deterministic
    user reason-coded DecisionRecord adoption point (design §5.4: Agent⑤
    never self-approves).  E0–E3/W1 and the four-layer finalization gate
    belong to other phases' cases and are intentionally not in this
    vocabulary: unknown Gate values fail closed at construction.
    """

    D1_DESIGN_CONSISTENCY = "D1"
    Q1_INDEPENDENT_QC = "Q1"
    USER_DECISION = "user_decision"


class OwnerRole(str, Enum):
    """Closed set of owners; mirrors product ``SkillDefinition.agent_role``.

    ``design_and_summary`` is Agent②, ``quality_control`` is Agent④,
    ``coordinator`` is Agent⑤ (matching the Phase 1 contract literal),
    ``user`` is the human decision maker, ``system`` is a deterministic
    check/calculation (no model, no I/O).
    """

    DESIGN_AND_SUMMARY = "design_and_summary"
    QUALITY_CONTROL = "quality_control"
    COORDINATOR = "coordinator"
    USER = "user"
    SYSTEM = "system"


class NodeKind(str, Enum):
    """Closed set of node kinds used by the three case graphs."""

    WORK = "work"  # agent-owned typed work node producing an artifact
    CHECK = "check"  # deterministic reducer/validator (system-owned)
    CALCULATION = "calculation"  # deterministic derivation (system-owned)
    DECISION = "decision"  # user decision/lock point


class EdgeKind(str, Enum):
    """Closed set of typed dependency edges between nodes."""

    DATA = "data"  # target consumes the source's output artifact
    DECISION = "decision"  # target consumes a decision record
    GATE = "gate"  # target requires the source's gate verdict


class SideEffectKind(str, Enum):
    """Closed set of declared side effects.

    Names follow the accepted Phase 1 ``SideEffectKind`` where they overlap
    (``none``, ``canonical_proposal``, ``artifact_create``);
    ``decision_record`` is the PoC addition for the reason-coded
    DecisionRecord writes the three cases need (design §5.4).  Side effects
    are *declared* only — Task 2.1 never executes them.
    """

    NONE = "none"
    CANONICAL_PROPOSAL = "canonical_proposal"
    ARTIFACT_CREATE = "artifact_create"
    DECISION_RECORD = "decision_record"


class InjectionKind(str, Enum):
    """Closed set of the five Task 2.1 injection classes.

    Every case graph must declare exactly one :class:`InjectionPoint` for
    each kind (validation ``CC_INJECTION_KIND_MISSING`` when absent,
    ``CC_INJECTION_KIND_DUPLICATE`` when repeated).  They are represented,
    never executed, per the frozen plan Task 2.1.
    """

    KILL_BEFORE = "kill_before"
    KILL_AFTER = "kill_after"
    DUPLICATE_RESUME = "duplicate_resume"
    CONCURRENT_DECISION = "concurrent_decision"
    OLD_GRAPH_MIGRATION = "old_graph_migration"


INJECTION_KINDS: Tuple[InjectionKind, ...] = (
    InjectionKind.KILL_BEFORE,
    InjectionKind.KILL_AFTER,
    InjectionKind.DUPLICATE_RESUME,
    InjectionKind.CONCURRENT_DECISION,
    InjectionKind.OLD_GRAPH_MIGRATION,
)


class FailurePolicy(str, Enum):
    """Closed set of allowed failure/retry semantics per node."""

    FAIL_CLOSED = "fail_closed"  # any failure blocks; explicit owner repair
    BOUNDED_RETRY = "bounded_retry"  # at most allowed_attempts, then fail closed


# ---------------------------------------------------------------------------
# Frozen JSON containers (mirror protocol_v3._FrozenJsonDict/_FrozenJsonList)
# ---------------------------------------------------------------------------


class FrozenJsonDict(dict):
    """JSON mapping that rejects mutation but serializes as a plain dict."""

    _IMMUTABLE_MESSAGE = "FrozenJsonDict is immutable"

    def __setitem__(self, key, value):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)

    def __delitem__(self, key):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)

    def clear(self):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)

    def pop(self, *args):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)

    def popitem(self):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)

    def setdefault(self, *args):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)

    def update(self, *args, **kwargs):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)


class FrozenJsonList(list):
    """JSON list that rejects mutation but serializes as a plain list."""

    _IMMUTABLE_MESSAGE = "FrozenJsonList is immutable"

    def __setitem__(self, key, value):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)

    def __delitem__(self, key):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)

    def append(self, value):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)

    def extend(self, values):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)

    def insert(self, index, value):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)

    def pop(self, *args):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)

    def remove(self, value):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)

    def reverse(self):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)

    def sort(self, *args, **kwargs):  # pragma: no cover - defensive
        raise TypeError(self._IMMUTABLE_MESSAGE)


# ---------------------------------------------------------------------------
# Deep immutability helpers
# ---------------------------------------------------------------------------


def freeze_input(value: Any) -> Any:
    """Recursively convert mutable JSON containers to frozen equivalents.

    ``dict`` -> :class:`FrozenJsonDict`, ``list`` -> :class:`FrozenJsonList`;
    tuples/frozensets/scalars pass through; ``set``/``bytearray`` (mutable,
    not JSON-serializable) are rejected.  Used by the fakes so no mutable
    nested input can enter a store.
    """
    if isinstance(value, dict):
        return FrozenJsonDict(
            (key, freeze_input(item)) for key, item in value.items()
        )
    if isinstance(value, list):
        return FrozenJsonList(freeze_input(item) for item in value)
    if isinstance(value, tuple):
        return tuple(freeze_input(item) for item in value)
    if isinstance(value, (set, frozenset)):
        raise CaseContractError(
            "CC_INPUT_NOT_JSONABLE", "input", "set/frozenset is not a JSON value"
        )
    if isinstance(value, bytearray):
        raise CaseContractError(
            "CC_INPUT_NOT_JSONABLE", "input", "bytearray is not a JSON value"
        )
    return value


def assert_deep_immutable(value: Any, *, path: str = "input") -> None:
    """Reject any *mutable* nested container at any depth (fail closed).

    Plain ``dict``/``list``/``set``/``bytearray`` fail with
    ``CC_INPUT_MUTABLE``; frozen containers (tuple, frozenset,
    :class:`FrozenJsonDict`, :class:`FrozenJsonList`) pass.
    """
    if isinstance(value, dict):
        if type(value) is dict:
            raise CaseContractError(
                "CC_INPUT_MUTABLE", path, "mutable dict nested in input"
            )
        for key, item in value.items():
            assert_deep_immutable(key, path=f"{path}.key")
            assert_deep_immutable(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        if type(value) is list:
            raise CaseContractError(
                "CC_INPUT_MUTABLE", path, "mutable list nested in input"
            )
        for index, item in enumerate(value):
            assert_deep_immutable(item, path=f"{path}[{index}]")
        return
    if isinstance(value, (set, bytearray)):
        raise CaseContractError(
            "CC_INPUT_MUTABLE", path, "mutable non-JSON container nested in input"
        )
    if isinstance(value, tuple):
        for index, item in enumerate(value):
            assert_deep_immutable(item, path=f"{path}[{index}]")
    # scalars, frozensets, enums, frozen models: immutable by construction


# ---------------------------------------------------------------------------
# Canonical JSON (mirror app.protocol_workflow.canonical.hashing.canonical_json)
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    """Convert a value to plain JSON-able Python, canonically."""
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise CaseContractError(
        "CC_INPUT_NOT_JSONABLE",
        "value",
        f"cannot canonicalize {type(value).__name__}",
    )


def canonical_json(value: Any) -> str:
    """Deterministic JSON serialization (sorted keys, compact separators)."""
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _material(value: Any) -> Any:
    """Structural serialization of a contract model (mirror protocol_v3._material_value)."""
    if isinstance(value, CaseContractModel):
        return {
            name: _material(getattr(value, name))
            for name in type(value).model_fields
            if name not in CaseContractModel.material_metadata_fields
        }
    if isinstance(value, dict):
        return {key: _material(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_material(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


class CaseContractModel(BaseModel):
    """Strict immutable contract base: frozen, closed, canonical hashable."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        use_enum_values=False,
        # Re-run validation on nested contract instances so a node/edge/
        # injection smuggled in with invalid fields (e.g. via model_copy
        # bypass) is still rejected when the graph is constructed.
        revalidate_instances="always",
    )

    #: Fields that are bookkeeping, not graph material.  Currently empty by
    #: design: the graph models carry *no* runtime/scheduler-private state,
    #: so the material hash cannot vary with when/how a graph was built.
    material_metadata_fields: ClassVar[frozenset[str]] = frozenset()

    def model_copy(
        self,
        *,
        update: Optional[dict[str, Any]] = None,
        deep: bool = False,
    ) -> "CaseContractModel":
        """Copy with full re-validation — never a silent validation bypass.

        Pydantic's default ``model_copy(update=...)`` does not re-run field
        or model validators, so a smuggled ``update`` (e.g.
        ``edges=("junk",)``) would produce an invalid graph that only
        crashes later, untyped, at hash time.  Rebuilding through the model
        constructor re-runs every field validator and every ``after`` model
        validator (``revalidate_instances="always"`` included), so invalid
        updates fail closed at the copy site with the usual typed errors.

        A copy without ``update`` returns ``self``: the models are frozen,
        an identical copy is indistinguishable, and returning the same
        object preserves immutability (nothing can mutate it).
        """
        if update is None:
            return self
        merged = self.model_dump()
        merged.update(update)
        return type(self)(**merged)


# ---------------------------------------------------------------------------
# Schema, node, edge, injection models
# ---------------------------------------------------------------------------


class SchemaDecl(CaseContractModel):
    """One declared output/input schema name of a case graph (closed set)."""

    name: NonEmptyText
    description: NonEmptyText


class NodeContract(CaseContractModel):
    """Immutable typed contract of one case-graph node.

    Declares the stable node id, kind, owner, Gate, typed precondition
    (consumed schema names), typed output schema, dependency ids, stable
    side-effect logical-key template and failure/retry semantics required by
    the frozen plan Task 2.1.
    """

    node_id: StableId
    kind: NodeKind
    owner: OwnerRole
    gate: GateKind
    #: Typed precondition/input contract: schema names this node consumes.
    #: Every name must be declared on the graph and covered by a dependency's
    #: output schema or a graph root input (validation CC_INPUT_UNCOVERED).
    inputs: Tuple[str, ...] = ()
    #: Typed output artifact/schema: one declared graph schema name.
    output_schema: NonEmptyText
    #: Dependency ids; must be exactly the sources of the edges targeting
    #: this node (validation CC_EDGE_UNMATCHED_DEPENDENCY).
    depends_on: Tuple[StableId, ...] = ()
    #: Stable side-effect logical-key template; required iff a side effect is
    #: declared.  Never executed by Task 2.1.
    side_effect_key_template: Optional[NonEmptyText] = None
    side_effect_kind: SideEffectKind = SideEffectKind.NONE
    failure_policy: FailurePolicy = FailurePolicy.FAIL_CLOSED
    allowed_attempts: PositiveRevision = 1

    @model_validator(mode="after")
    def _validate_node_contract(self) -> "NodeContract":
        if len(self.inputs) != len(set(self.inputs)):
            raise CaseContractError(
                "CC_INPUT_DUPLICATE",
                f"nodes/{self.node_id}/inputs",
                "input schema names must be unique",
            )
        if len(self.depends_on) != len(set(self.depends_on)):
            raise CaseContractError(
                "CC_DEPENDENCY_DUPLICATE",
                f"nodes/{self.node_id}/depends_on",
                "dependency ids must be unique",
            )
        if self.side_effect_kind is SideEffectKind.NONE:
            if self.side_effect_key_template is not None:
                raise CaseContractError(
                    "CC_SIDE_EFFECT_KEY_UNEXPECTED",
                    f"nodes/{self.node_id}/side_effect_key_template",
                    "a node without a declared side effect must not carry a key template",
                )
        elif self.side_effect_key_template is None:
            raise CaseContractError(
                "CC_SIDE_EFFECT_KEY_MISSING",
                f"nodes/{self.node_id}",
                "a node declaring a side effect must declare a stable logical-key template",
            )
        if self.failure_policy is FailurePolicy.FAIL_CLOSED:
            if self.allowed_attempts != 1:
                raise CaseContractError(
                    "CC_FAILURE_POLICY",
                    f"nodes/{self.node_id}/allowed_attempts",
                    "fail_closed nodes allow exactly one attempt",
                )
        elif self.allowed_attempts < 2:
            raise CaseContractError(
                "CC_FAILURE_POLICY",
                f"nodes/{self.node_id}/allowed_attempts",
                "bounded_retry requires at least two allowed attempts",
            )
        return self


class Edge(CaseContractModel):
    """Typed dependency edge; both endpoints must be declared nodes."""

    source_node_id: StableId
    target_node_id: StableId
    kind: EdgeKind


class InjectionPoint(CaseContractModel):
    """One explicit injection declaration; represented, never executed.

    ``target_node_id`` names the node the injection applies to (required for
    kill/duplicate/concurrent kinds); ``old_graph_migration`` is graph-level
    and instead pins ``old_graph_version``.  ``logical_key`` is the stable
    logical key the injection is bound to; ``expectation`` describes the
    fail-closed behavior a later Task 2.1/2.2 test must verify.
    """

    injection_kind: InjectionKind
    target_node_id: Optional[StableId] = None
    logical_key: NonEmptyText
    expectation: NonEmptyText
    old_graph_version: Optional[NonEmptyText] = None

    @model_validator(mode="after")
    def _validate_injection_point(self) -> "InjectionPoint":
        if self.injection_kind is InjectionKind.OLD_GRAPH_MIGRATION:
            if self.old_graph_version is None:
                raise CaseContractError(
                    "CC_INJECTION_MIGRATION",
                    f"injections/{self.injection_kind.value}",
                    "old_graph_migration must pin old_graph_version",
                )
            if self.target_node_id is not None:
                raise CaseContractError(
                    "CC_INJECTION_MIGRATION",
                    f"injections/{self.injection_kind.value}",
                    "old_graph_migration is graph-level and must not name a node",
                )
        else:
            if self.old_graph_version is not None:
                raise CaseContractError(
                    "CC_INJECTION_MIGRATION",
                    f"injections/{self.injection_kind.value}",
                    "old_graph_version is only valid for old_graph_migration",
                )
            if self.target_node_id is None:
                raise CaseContractError(
                    "CC_INJECTION_TARGET",
                    f"injections/{self.injection_kind.value}",
                    "injection must name a target node",
                )
        return self


# ---------------------------------------------------------------------------
# Case graph
# ---------------------------------------------------------------------------


class CaseGraph(CaseContractModel):
    """A closed, immutable, deterministic definition of one PoC case graph.

    Binds ``case_id``/``project_id``/``branch_id``, the graph contract schema
    version and a per-case ``graph_version`` to a deterministic material
    SHA-256.  No executable scheduler, clinical truth or runtime state lives
    in the graph: it is a pure typed definition.

    Construction fails closed (raises ``pydantic.ValidationError`` wrapping
    :class:`CaseContractError`) on: duplicate/unknown nodes, duplicate
    schema or root-input declarations, unknown dependencies, edges
    inconsistent with declared ``depends_on``, cycles, invalid
    owner/Gate/schema, dangling/duplicate inputs, missing or duplicated
    injection classes, unknown injection targets and schema-version
    mismatch.
    """

    case_id: CaseId
    project_id: StableId
    branch_id: StableId
    schema_version: Literal["mw_protocol_v3_orchestrator_case_contract_v1"] = (
        CASE_CONTRACT_SCHEMA_VERSION
    )
    graph_version: NonEmptyText
    description: NonEmptyText
    #: Closed per-case schema vocabulary (output artifacts + root inputs).
    schemas: Tuple[SchemaDecl, ...] = Field(min_length=1)
    #: Schema names the graph can be seeded with (e.g. study facts,
    #: evidence units, labeled synthetic assumption sets).
    root_inputs: Tuple[str, ...] = ()
    nodes: Tuple[NodeContract, ...] = Field(min_length=1)
    edges: Tuple[Edge, ...] = ()
    # Coverage of all five injection kinds is enforced by the validator
    # (CC_INJECTION_KIND_MISSING lists the missing kinds explicitly).
    injections: Tuple[InjectionPoint, ...] = ()

    @model_validator(mode="after")
    def _validate_graph(self) -> "CaseGraph":
        self._assert_closed_vocabulary()
        self._assert_edges_and_acyclicity()
        self._assert_input_coverage()
        self._assert_injections()
        return self

    # -- validation ---------------------------------------------------------

    def _schema_names(self) -> frozenset[str]:
        return frozenset(schema.name for schema in self.schemas)

    def _assert_closed_vocabulary(self) -> None:
        # Duplicate detection MUST read the raw ``schemas`` sequence: the
        # frozenset helper would silently dedupe before the check can fire.
        raw_schema_names = [schema.name for schema in self.schemas]
        if len(raw_schema_names) != len(set(raw_schema_names)):
            raise CaseContractError(
                "CC_SCHEMA_DUPLICATE", "schemas", "schema names must be unique"
            )
        if len(self.root_inputs) != len(set(self.root_inputs)):
            raise CaseContractError(
                "CC_ROOT_INPUT_DUPLICATE",
                "root_inputs",
                "root input schema names must be unique",
            )
        schema_names = self._schema_names()
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise CaseContractError(
                "CC_NODE_DUPLICATE", "nodes", "node ids must be unique"
            )
        for node in self.nodes:
            if node.output_schema not in schema_names:
                raise CaseContractError(
                    "CC_SCHEMA_UNKNOWN",
                    f"nodes/{node.node_id}/output_schema",
                    f"unknown output schema {node.output_schema!r}",
                )
            for input_name in node.inputs:
                if input_name not in schema_names:
                    raise CaseContractError(
                        "CC_SCHEMA_UNKNOWN",
                        f"nodes/{node.node_id}/inputs",
                        f"unknown input schema {input_name!r}",
                    )
        for input_name in self.root_inputs:
            if input_name not in schema_names:
                raise CaseContractError(
                    "CC_SCHEMA_UNKNOWN",
                    "root_inputs",
                    f"unknown root input schema {input_name!r}",
                )

    def _assert_edges_and_acyclicity(self) -> None:
        node_ids = frozenset(node.node_id for node in self.nodes)
        seen_edges: set[Tuple[str, str, str]] = set()
        for edge in self.edges:
            if edge.source_node_id not in node_ids:
                raise CaseContractError(
                    "CC_EDGE_UNKNOWN_NODE",
                    f"edges/{edge.source_node_id}",
                    "edge references an unknown source node",
                )
            if edge.target_node_id not in node_ids:
                raise CaseContractError(
                    "CC_EDGE_UNKNOWN_NODE",
                    f"edges/{edge.target_node_id}",
                    "edge references an unknown target node",
                )
            if edge.source_node_id == edge.target_node_id:
                raise CaseContractError(
                    "CC_EDGE_SELF",
                    f"edges/{edge.source_node_id}",
                    "self dependency edges are not allowed",
                )
            key = (edge.source_node_id, edge.target_node_id, edge.kind.value)
            if key in seen_edges:
                raise CaseContractError(
                    "CC_EDGE_DUPLICATE",
                    f"edges/{edge.source_node_id}->{edge.target_node_id}",
                    "duplicate dependency edge",
                )
            seen_edges.add(key)
        # depends_on must be exactly the incoming edge sources (single source
        # of truth: both declarations must agree or the graph fails closed).
        incoming: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        for edge in self.edges:
            incoming[edge.target_node_id].add(edge.source_node_id)
        for node in self.nodes:
            declared = set(node.depends_on)
            if node.node_id in declared:
                raise CaseContractError(
                    "CC_EDGE_SELF",
                    f"nodes/{node.node_id}/depends_on",
                    "a node must not depend on itself",
                )
            if declared != incoming[node.node_id]:
                raise CaseContractError(
                    "CC_EDGE_UNMATCHED_DEPENDENCY",
                    f"nodes/{node.node_id}/depends_on",
                    "declared dependencies must equal incoming edge sources",
                )
        # Acyclicity: the shared deterministic Kahn core (distinct-source /
        # distinct-target bookkeeping).  Parallel typed edges between the
        # same pair share one prerequisite slot, so they can never overshoot
        # a decrement and mask a real cycle.
        _, remaining = self._distinct_dependency_kahn()
        if remaining:
            raise CaseContractError(
                "CC_CYCLE",
                "edges",
                f"graph contains a cycle among nodes: {sorted(remaining)}",
            )

    def _distinct_dependency_kahn(self) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        """Shared deterministic Kahn core over distinct dependencies.

        Single source of truth for acyclicity/ordering: both construction
        validation (:meth:`_assert_edges_and_acyclicity`) and the read
        helper :meth:`topological_order` call this, so they cannot drift.

        Indegree counts *distinct* upstream nodes and each completed source
        decrements each distinct target at most once — parallel typed edges
        (DATA and GATE) between the same pair share one prerequisite slot,
        so a node is only released once every upstream source is done and a
        real cycle can never be masked by an overshooting decrement.
        Edges whose endpoints are not declared nodes are ignored (a read
        helper must not crash on a bypassed instance; construction already
        rejects such edges with ``CC_EDGE_UNKNOWN_NODE``).

        Returns ``(ordered, remaining)`` with node_id tie-break.
        """
        node_ids = frozenset(node.node_id for node in self.nodes)
        incoming: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        successors: dict[str, set[str]] = {
            node_id: set() for node_id in node_ids
        }
        for edge in self.edges:
            source = edge.source_node_id
            target = edge.target_node_id
            if source in node_ids:
                successors[source].add(target)
            if target in node_ids:
                incoming[target].add(source)
        indegree = {node_id: len(incoming[node_id]) for node_id in node_ids}
        ready = sorted(
            node_id for node_id in node_ids if indegree[node_id] == 0
        )
        ordered: list[str] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for target in sorted(successors[current]):
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
                    ready.sort()
        remaining = tuple(
            sorted(node_id for node_id in node_ids if indegree[node_id] > 0)
        )
        return tuple(ordered), remaining

    def _assert_input_coverage(self) -> None:
        node_by_id = {node.node_id: node for node in self.nodes}
        root = frozenset(self.root_inputs)
        for node in self.nodes:
            produced = frozenset(
                node_by_id[dep].output_schema for dep in node.depends_on
            )
            covered = produced | root
            for input_name in node.inputs:
                if input_name not in covered:
                    raise CaseContractError(
                        "CC_INPUT_UNCOVERED",
                        f"nodes/{node.node_id}/inputs",
                        f"input schema {input_name!r} is produced by no dependency "
                        "and is not a root input",
                    )

    def _assert_injections(self) -> None:
        declared = [point.injection_kind for point in self.injections]
        # Each injection kind must be declared exactly once; the set
        # comprehension below would silently dedupe, so count the raw list.
        duplicated = [
            kind.value for kind in INJECTION_KINDS if declared.count(kind) > 1
        ]
        if duplicated:
            raise CaseContractError(
                "CC_INJECTION_KIND_DUPLICATE",
                "injections",
                f"each injection kind must be declared exactly once; "
                f"duplicated: {duplicated}",
            )
        declared_kinds = set(declared)
        missing = [
            kind.value for kind in INJECTION_KINDS if kind not in declared_kinds
        ]
        if missing:
            raise CaseContractError(
                "CC_INJECTION_KIND_MISSING",
                "injections",
                f"case must declare injection points for: {missing}",
            )
        node_ids = frozenset(node.node_id for node in self.nodes)
        for point in self.injections:
            if (
                point.target_node_id is not None
                and point.target_node_id not in node_ids
            ):
                raise CaseContractError(
                    "CC_INJECTION_TARGET",
                    f"injections/{point.injection_kind.value}",
                    f"unknown target node {point.target_node_id!r}",
                )

    # -- read helpers -------------------------------------------------------

    def node(self, node_id: str) -> NodeContract:
        """Return the declared node or fail closed (``CC_NODE_UNKNOWN``)."""
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise CaseContractError(
            "CC_NODE_UNKNOWN", f"nodes/{node_id}", f"unknown node {node_id!r}"
        )

    def node_dependencies(self, node_id: str) -> Tuple[str, ...]:
        """Sorted distinct dependency ids of one node (derived from edges).

        Parallel typed edges (DATA and GATE) between the same pair count as
        one dependency: the result has no duplicate ids and matches the
        node's declared ``depends_on`` exactly (distinct sources, sorted).
        """
        node_ids = frozenset(node.node_id for node in self.nodes)
        if node_id not in node_ids:
            raise CaseContractError(
                "CC_NODE_UNKNOWN", f"nodes/{node_id}", f"unknown node {node_id!r}"
            )
        return tuple(
            sorted(
                {
                    edge.source_node_id
                    for edge in self.edges
                    if edge.target_node_id == node_id
                }
            )
        )

    def topological_order(self) -> Tuple[str, ...]:
        """Deterministic dependency order (graph is acyclic by construction).

        Uses the shared Kahn core (:meth:`_distinct_dependency_kahn`), so
        parallel typed edges share one prerequisite slot.  Fails closed with
        ``CC_CYCLE`` instead of returning a partial order when a malformed /
        bypassed instance cannot order every declared node.
        """
        ordered, remaining = self._distinct_dependency_kahn()
        if remaining:
            raise CaseContractError(
                "CC_CYCLE",
                "edges",
                f"graph contains a cycle among nodes: {sorted(remaining)}",
            )
        return ordered

    def injection_kinds(self) -> Tuple[str, ...]:
        """Sorted declared injection kinds (values)."""
        return tuple(sorted(point.injection_kind.value for point in self.injections))

    # -- material hash ------------------------------------------------------

    def material_payload(self) -> dict[str, Any]:
        """Canonical structural payload; identity + sorted structure only.

        No timestamps, run ids, sessions or counters exist on the models, so
        the payload cannot carry scheduler-private state.  Sorting by id
        makes the hash stable across equivalent construction order.
        """
        nodes = sorted(
            (_material(node) for node in self.nodes),
            key=lambda item: item["node_id"],
        )
        edges = sorted(
            (_material(edge) for edge in self.edges),
            key=lambda item: (
                item["source_node_id"],
                item["target_node_id"],
                item["kind"],
            ),
        )
        injections = sorted(
            (_material(point) for point in self.injections),
            key=lambda item: (
                item["injection_kind"],
                item.get("target_node_id") or "",
                item["logical_key"],
            ),
        )
        schemas = sorted(
            (_material(schema) for schema in self.schemas),
            key=lambda item: item["name"],
        )
        return {
            "case_id": self.case_id.value,
            "project_id": self.project_id,
            "branch_id": self.branch_id,
            "schema_version": self.schema_version,
            "graph_version": self.graph_version,
            "description": self.description,
            "schemas": schemas,
            "root_inputs": sorted(self.root_inputs),
            "nodes": nodes,
            "edges": edges,
            "injections": injections,
        }

    def material_sha256(self) -> str:
        """Deterministic SHA-256 of the material payload (64 hex chars)."""
        payload = json.dumps(
            self.material_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Binding guard
# ---------------------------------------------------------------------------


def assert_case_graph_binding(
    graph: CaseGraph, project_id: str, branch_id: str
) -> None:
    """Fail closed when a graph is not bound to the given project/branch."""
    if graph.project_id != project_id or graph.branch_id != branch_id:
        raise CaseContractError(
            "CC_BINDING_MISMATCH",
            "graph",
            f"graph {graph.case_id.value} is bound to "
            f"{graph.project_id}/{graph.branch_id}, not {project_id}/{branch_id}",
        )
