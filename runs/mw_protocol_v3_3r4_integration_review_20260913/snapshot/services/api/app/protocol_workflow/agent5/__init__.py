"""Agent⑤ orchestration control surface (Protocol v3 Task 1.9).

Design authority: Protocol v3 multi-agent rearchitecture design sections 5.3
(versioned skill registry), 5.4 (Agent⑤ coordination boundary), 18 (run
isolation / recovery / error handling) and the frozen plan Task 1.9.

Agent⑤ is the only user-side workflow coordination role.  It can pin a run
manifest from already approved inputs, decompose registered coordinator work
into a deterministic dependency order, aggregate progress/versions/Gate
observations without changing them, build a decision/request queue
representation and generate user-facing exception cards with strictly
separated public/audit payloads.

It cannot mutate clinical facts, create an unowned ``DecisionRecord``, change
finding severity, lower/override/skip a Gate, replace the Agent④ clean
verdict, redefine a stable denominator, relabel failed/unknown/interrupted
work as complete or independently assert ``可提交定稿``.

Public surface
--------------
* ``run_manifest`` — immutable closed value objects: ``RegistrySelection``,
  ``PinnedSkill``, ``TemplatePin``, ``GraphPin``, ``RunManifest``,
  ``WorkPackageSpec``, ``CoordinatorWorkPackage``, ``WorkPackageGraph``,
  ``GateResult``, ``GateObservation``, ``GateSummary``, ``ProgressSummary``,
  ``DecisionRequest``, ``DecisionRequestQueue``.
* ``coordinator`` — ``Agent5QueryFacade`` (narrow read-only query snapshot
  adapter; executes the typed queries once through the application service
  and retains only the frozen results) and ``Agent5Coordinator`` (the control
  surface itself).
* ``exception_cards`` — ``ExceptionCard`` with split public/audit payloads.
"""

from __future__ import annotations

from .coordinator import Agent5Coordinator, Agent5QueryFacade
from .exception_cards import (
    ExceptionCard,
    ExceptionCardAuditPayload,
    ExceptionCardPublicPayload,
)
from .run_manifest import (
    CoordinatorWorkPackage,
    DecisionRequest,
    DecisionRequestQueue,
    GateObservation,
    GateResult,
    GateSummary,
    GraphPin,
    PinnedSkill,
    ProgressSummary,
    RegistrySelection,
    RunManifest,
    TemplatePin,
    WorkPackageGraph,
    WorkPackageSpec,
)

__all__ = [
    # coordinator
    "Agent5Coordinator",
    "Agent5QueryFacade",
    # exception cards
    "ExceptionCard",
    "ExceptionCardAuditPayload",
    "ExceptionCardPublicPayload",
    # value objects
    "CoordinatorWorkPackage",
    "DecisionRequest",
    "DecisionRequestQueue",
    "GateObservation",
    "GateResult",
    "GateSummary",
    "GraphPin",
    "PinnedSkill",
    "ProgressSummary",
    "RegistrySelection",
    "RunManifest",
    "TemplatePin",
    "WorkPackageGraph",
    "WorkPackageSpec",
]
