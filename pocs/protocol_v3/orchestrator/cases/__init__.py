"""Protocol v3 orchestrator PoC — case registry scaffolding (Task 2.1).

Worker 01 owns this file; the three case *definitions* are owned by
Worker 02 (``eligibility.py``, ``objective_estimand_endpoint.py``) and
Worker 03 (``sample_size.py``).

This module re-exports the shared immutable vocabulary so case authors and
the integrated test import from one surface (``orchestrator.cases``), pins
the closed :class:`CaseId` registry to the three module names, and provides
the lazy loader / closure checks the Task 2.1 tests use:

* each case module must export ``GRAPH: CaseGraph`` whose ``case_id``
  matches the registry key (``CC_CASE_MODULE_GRAPH`` /
  ``CC_CASE_ID_MISMATCH`` otherwise);
* :func:`iter_case_graphs` loads all three in deterministic order;
* :func:`assert_registry_closed` fails closed if any of the three cases is
  missing from a loaded set.

Loading is lazy (``importlib`` at call time), so importing this package
never touches case modules that a worker may still be writing.  PoC-only;
MUST NOT be imported by product code.
"""

from __future__ import annotations

import importlib
from types import MappingProxyType
from typing import Mapping, Tuple

from .. import (
    CASE_CONTRACT_SCHEMA_VERSION,
    CASE_IDS,
    INJECTION_KINDS,
    AwareDateTime,
    CaseContractError,
    CaseGraph,
    CaseId,
    Edge,
    EdgeKind,
    FailurePolicy,
    FrozenJsonDict,
    FrozenJsonList,
    GateKind,
    InjectionKind,
    InjectionPoint,
    NodeContract,
    NodeKind,
    NonEmptyText,
    OwnerRole,
    PositiveRevision,
    SchemaDecl,
    Sha256,
    SideEffectKind,
    StableId,
    assert_case_graph_binding,
    assert_deep_immutable,
    canonical_json,
    freeze_input,
)

__all__ = [
    "CASE_CONTRACT_SCHEMA_VERSION",
    "CASE_IDS",
    "INJECTION_KINDS",
    "CASE_MODULES",
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
    "StableId",
    "Sha256",
    "NonEmptyText",
    "AwareDateTime",
    "PositiveRevision",
    "FrozenJsonDict",
    "FrozenJsonList",
    "freeze_input",
    "assert_deep_immutable",
    "assert_case_graph_binding",
    "canonical_json",
    "case_graph",
    "load_case",
    "iter_case_graphs",
    "assert_registry_closed",
]

#: Registry key -> case module name (inside this package).  Immutable.
CASE_MODULES: Mapping[CaseId, str] = MappingProxyType(
    {
        CaseId.ELIGIBILITY: "eligibility",
        CaseId.OBJECTIVE_ESTIMAND_ENDPOINT: "objective_estimand_endpoint",
        CaseId.SAMPLE_SIZE: "sample_size",
    }
)


def case_graph(**kwargs: object) -> CaseGraph:
    """Convenience validated constructor (all keyword arguments pass
    straight through to :class:`CaseGraph`)."""
    return CaseGraph(**kwargs)


def load_case(case_id: CaseId) -> CaseGraph:
    """Import the case module for *case_id* and return its ``GRAPH``.

    The case module must export ``GRAPH: CaseGraph`` bound to the requested
    ``case_id``; anything else fails closed.
    """
    module_name = CASE_MODULES[case_id]
    module = importlib.import_module(f"{__name__}.{module_name}")
    graph = getattr(module, "GRAPH", None)
    if not isinstance(graph, CaseGraph):
        raise CaseContractError(
            "CC_CASE_MODULE_GRAPH",
            f"cases/{module_name}",
            "case module must export GRAPH: CaseGraph",
        )
    if graph.case_id != case_id:
        raise CaseContractError(
            "CC_CASE_ID_MISMATCH",
            f"cases/{module_name}",
            f"module exports case {graph.case_id.value!r}, expected {case_id.value!r}",
        )
    return graph


def iter_case_graphs() -> Tuple[CaseGraph, ...]:
    """Load all three Task 2.1 case graphs in deterministic registry order."""
    return tuple(load_case(case_id) for case_id in CASE_IDS)


def assert_registry_closed(graphs: Tuple[CaseGraph, ...]) -> None:
    """Fail closed unless *graphs* contains exactly the three Task 2.1 cases.

    Used by the integrated test to prove the case registry is closed: no
    case may be missing and no foreign case may be smuggled in (the latter
    is structurally impossible while :class:`CaseId` stays closed, but the
    check keeps the invariant explicit).
    """
    seen = {graph.case_id for graph in graphs}
    missing = [case_id.value for case_id in CASE_IDS if case_id not in seen]
    if missing:
        raise CaseContractError(
            "CC_CASE_REGISTRY_OPEN",
            "cases",
            f"case registry is missing: {missing}",
        )
    foreign = [case_id.value for case_id in seen if case_id not in CASE_IDS]
    if foreign:
        raise CaseContractError(
            "CC_CASE_REGISTRY_OPEN",
            "cases",
            f"case registry contains foreign cases: {foreign}",
        )
