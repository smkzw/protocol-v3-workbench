"""Protocol v3 Harness policy boundary and typed minimal artifact contracts.

This module is the deterministic, fail-closed policy boundary that sits between
a :class:`NodeExecutionContract` (frozen Task 1.6) and an injected transport
adapter (Direct API, local oMLX, Codex App/CLI, OMP CLI — see
:mod:`runtime.adapters`).  It is part of frozen Task 1.7.

Design authority: ``plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md``
sections 17.2 and 18, plus the accepted Task 1.7 contract.

The harness enforces the offline discipline mandated by the plan:

* **Registry-bound role policy.**  Role thinking/effort discipline, target
  provider/model/harness and sensitivity ceiling come from the immutable
  :class:`~app.protocol_workflow.registries.loader.RoleEntry` loaded by the
  strict registry loader.  No caller-supplied boolean can mark a frozen role
  as thinking-capable.

* **Full node/skill/artifact binding.**  The node contract's
  ``skill_definition_id`` must equal the skill's id; the node's input/output
  schema refs must equal the skill's refs; the exact passed artifact hash
  tuple must match the contract's versioned dependency binding (no substitution,
  omission, duplicate or reordering).  Contract tools/paths are always
  enforced as subsets of the skill's closed set, even when the skill set is
  empty.

* **Artifact-only input.**  The harness accepts only immutable artifact
  references (content-addressed by sha256) plus explicitly bounded snippets.
  Artifact refs are closed logical URIs/IDs — never absolute paths, home
  paths, traversal or control strings.  Any credential-shaped value inside a
  request fails closed before dispatch.

* **Selected region and sensitivity.**  An explicit selected target region is
  required and must appear in both the node allowlist and the Role
  target-profile regions.  The Role target-profile sensitivity tier is the
  maximum permitted tier; a more sensitive request is rejected.

* **Unified workload gate.**  For role kinds ``ocr`` and ``translation`` the
  harness requires an injected read-only effective model selection plus a
  real injected lease context factory.  The declared model is compared to the
  effective model before probe/dispatch; a missing or mismatched selection
  fails closed.  The correct ``ocr``/``translation`` lease is held around the
  single transport call.  This applies to Paddle Direct API and local oMLX
  equally — the registered Paddle OCR harness is Direct API, so the gate
  cannot be enforced only inside the local oMLX adapter.

* **Probe-once-per-identity.**  Every adapter must pass a first-use
  connectivity probe; only a successful probe is cached.  A probe failure
  fails closed and is never retried automatically.

* **No latency re-dispatch.**  The harness never sets ``max_turns=1`` and never
  automatically re-dispatches on latency or an unknown outcome.

* **Accurate dispatched semantics.**  Preflight/policy/probe/gate/lease-
  acquisition failures report ``dispatched=False`` and zero transport calls.
  ``dispatched=True`` is set only when entering the injected physical
  transport boundary.

The harness performs no network, model, OCR, translation, repository or
filesystem write access.  All physical side effects are injected.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Protocol, runtime_checkable

from app.protocol_workflow.registries.loader import RoleEntry
from app.protocol_workflow.runtime.idempotency import (
    FallbackSafetyViolation,
    canonical_input_hash,
    rebuild_fallback_payload,
)

from packages.contracts.workbench_contracts.protocol_v3 import (
    NodeExecutionContract,
    ReasoningEffort,
    SensitivityTier,
    SkillDefinition,
)

__all__ = [
    "AdapterOutcome",
    "AdapterProbeError",
    "ArtifactRef",
    "DispatchReceipt",
    "FallbackInput",
    "GateLeaseFactory",
    "GateSelection",
    "HarnessDispatchRequest",
    "HarnessDispatchResult",
    "HarnessError",
    "HarnessFallbackError",
    "HarnessPolicyError",
    "HarnessResult",
    "ProbePolicy",
    "Transport",
    "TransportAdapter",
    "build_fallback_request",
    "build_request",
]

# ---------------------------------------------------------------------------
# Credential scanner (defence-in-depth, mirrors the registry loader)
# ---------------------------------------------------------------------------

#: Keys that smell like credentials.  Matched case-insensitively against the
#: whole key.  Harness requests must be credential-free, exactly like the
#: registry documents (see ``registries.loader.CREDENTIAL_KEY_RE``).
_CREDENTIAL_KEY_RE = re.compile(
    r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|client[_-]?secret|bearer|authorization|credential)"
)

#: Values that smell like credentials: bearer tokens, private key headers,
#: ``sk-`` prefixed secrets and AWS-style access-key ids.  This mirrors the
#: accepted registry loader pattern exactly (see
#: ``registries.loader.CREDENTIAL_VALUE_RE``); it deliberately does NOT match
#: arbitrary hex strings so that legitimate sha256 content hashes are not
#: false-positives.
_CREDENTIAL_VALUE_RE = re.compile(
    r"(?i)(Bearer\s+[A-Za-z0-9._\-]+|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})"
)


def _scan_credentials(node: Any, location: str) -> None:
    """Recursively reject credential-shaped keys or values.

    Raises :class:`HarnessPolicyError` on the first hit so the harness fails
    closed *before* any adapter is selected or probed.
    """
    if isinstance(node, Mapping):
        for key, item in node.items():
            key_text = str(key)
            if _CREDENTIAL_KEY_RE.search(key_text):
                raise HarnessPolicyError(
                    f"credential-shaped key rejected at {location}: {key_text!r}"
                )
            if isinstance(item, str) and _CREDENTIAL_VALUE_RE.search(item):
                raise HarnessPolicyError(
                    f"credential-shaped value rejected at {location}.{key_text}"
                )
            _scan_credentials(item, f"{location}.{key_text}")
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            _scan_credentials(item, f"{location}[{index}]")


# ---------------------------------------------------------------------------
# Logical artifact-ref validation
# ---------------------------------------------------------------------------

#: Artifact refs must be closed logical URIs/IDs.  They must NOT be absolute
#: paths, home paths, traversal fragments or arbitrary filesystem paths.  The
#: accepted form is a stable-id-like logical name optionally slash-separated
#: into a namespace (e.g. ``seed``, ``chapter-1/draft``, ``ocr/page-3``).
#: Leading/trailing slashes, ``~``, ``..``, backslash and control chars are
#: rejected.
_ARTIFACT_REF_RE = re.compile(r"^[a-z][a-z0-9]*(?:[/_:-][a-z0-9]+)*$")

#: Characters that signal a filesystem path rather than a logical ref.
_PATH_ESCAPE_RE = re.compile(r"(^\s*/)|(^~/)|(^~$)|(\.\./)|(\.\.\\)|(\\)")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HarnessError(RuntimeError):
    """Base class for deterministic harness failures."""


class HarnessPolicyError(HarnessError):
    """A pre-dispatch policy check failed.

    Raising this error guarantees that **no** adapter was probed or invoked.
    The message is safe to surface to the user and the audit trail; it never
    embeds the rejected credential value.
    """


class AdapterProbeError(HarnessError):
    """The first-use connectivity probe for an adapter identity failed.

    A failed probe is cached as a negative result so the harness does not
    retry probes automatically.  Only an explicit policy reconciliation can
    clear a cached probe failure.
    """


class HarnessFallbackError(HarnessError):
    """A fallback request is ineligible or cannot be made safe."""


class WorkloadGateError(HarnessPolicyError):
    """A workload-gate policy violation for OCR/translation role kinds.

    Raised when the injected effective gate model selection is missing or does
    not match the declared role model, or when the required lease factory was
    not injected.  This is a stable pre-dispatch policy error.
    """


# ---------------------------------------------------------------------------
# Immutable typed artifact contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactRef:
    """A single immutable, content-addressed artifact reference.

    The harness never accepts repositories, credentials or arbitrary
    filesystem paths.  Every input artifact is described by its logical ref
    name plus a sha256 content hash; an optional bounded snippet may carry the
    minimal material the adapter actually needs.

    ``ref`` must be a closed logical artifact URI/ID — never an absolute path,
    home path, traversal fragment, control string or arbitrary filesystem
    path.
    """

    ref: str
    sha256: str
    snippet: str = ""

    def __post_init__(self) -> None:
        raw_ref = self.ref
        ref = raw_ref.strip()
        if not ref:
            raise HarnessPolicyError("artifact ref name must be non-empty")
        if any(char in ref for char in ("\n", "\r", "\t")):
            raise HarnessPolicyError(
                f"artifact ref name must not contain whitespace control chars: {ref!r}"
            )
        # Reject filesystem-path shapes.
        if _PATH_ESCAPE_RE.search(ref):
            raise HarnessPolicyError(
                f"artifact ref must be a logical URI/ID, not a path: {ref!r}"
            )
        if "/" in ref and ref.startswith("/"):
            raise HarnessPolicyError(
                f"artifact ref must not be an absolute path: {ref!r}"
            )
        if not _ARTIFACT_REF_RE.fullmatch(ref):
            raise HarnessPolicyError(
                f"artifact ref must be a closed logical id "
                f"(lowercase alphanumerics, '/_', ':', '-' separators): {ref!r}"
            )
        sha = self.sha256.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise HarnessPolicyError(
                f"artifact sha256 must be a 64-char hex digest: {self.sha256!r}"
            )
        # Bounded snippet: capped to keep the harness input minimal.
        if len(self.snippet) > 8192:
            raise HarnessPolicyError(
                f"artifact snippet for {ref!r} exceeds the 8192-char bound"
            )
        # frozen=True dataclass: bypass __setattr__ via object.__setattr__.
        object.__setattr__(self, "ref", ref)
        object.__setattr__(self, "sha256", sha)


@dataclass(frozen=True)
class _RequestBindingEvidence:
    """Authoritative inputs retained only for dispatcher revalidation."""

    node_contract: NodeExecutionContract
    skill: SkillDefinition
    role_entry: RoleEntry
    artifacts: tuple[ArtifactRef, ...]
    selected_region: str
    node_contract_snapshot: str
    skill_snapshot: str
    role_entry_snapshot: str
    artifact_snapshot: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class HarnessDispatchRequest:
    """The minimal, policy-validated input handed to an injected transport.

    The request carries *only* canonical artifact references, explicitly
    bounded snippets, the resolved provider/model/effort, the logical call
    identity and the same-session recovery handle.  It never carries
    credentials, repository handles, raw previous-provider scratchpads or
    session transcripts.
    """

    node_execution_contract_id: str
    skill_definition_id: str
    role: str
    role_kind: str
    harness: str
    provider: str
    model: str
    reasoning_effort: ReasoningEffort
    input_artifacts: tuple[ArtifactRef, ...]
    input_schema_ref: str
    output_schema_ref: str
    allowed_tools: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    sensitivity_tier: SensitivityTier
    selected_region: str
    allowed_providers: tuple[str, ...]
    allowed_regions: tuple[str, ...]
    logical_call_id: str
    idempotency_key: str
    prompt_sha256: str
    same_session_recovery: bool
    provider_session_id: str | None = None
    # Authoritative binding inputs are never serialized to the transport
    # payload.  The dispatcher reruns every binding check from this evidence
    # and compares the rebuilt canonical fields before probe/transport.  Direct
    # construction leaves evidence absent and therefore fails closed.
    _binding_evidence: _RequestBindingEvidence | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-serialisable, credential-free dispatch payload.

        The payload contains only the material the adapter needs; it is built
        from the immutable artifact references, never from a raw repository
        or scratchpad handle.
        """
        return {
            "node_execution_contract_id": self.node_execution_contract_id,
            "skill_definition_id": self.skill_definition_id,
            "role": self.role,
            "role_kind": self.role_kind,
            "harness": self.harness,
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort.value,
            "input_artifacts": [
                {
                    "ref": artifact.ref,
                    "sha256": artifact.sha256,
                    "snippet": artifact.snippet,
                }
                for artifact in self.input_artifacts
            ],
            "input_schema_ref": self.input_schema_ref,
            "output_schema_ref": self.output_schema_ref,
            "allowed_tools": list(self.allowed_tools),
            "allowed_paths": list(self.allowed_paths),
            "sensitivity_tier": self.sensitivity_tier.value,
            "selected_region": self.selected_region,
            "allowed_providers": list(self.allowed_providers),
            "allowed_regions": list(self.allowed_regions),
            "logical_call_id": self.logical_call_id,
            "idempotency_key": self.idempotency_key,
            "prompt_sha256": self.prompt_sha256,
            "same_session_recovery": self.same_session_recovery,
            "provider_session_id": self.provider_session_id,
        }


@dataclass(frozen=True)
class DispatchReceipt:
    """The typed receipt returned by a transport adapter on a successful call.

    The receipt owns the observed provider/model identity (runtime authority,
    never registry text), the output content hash, a logical output artifact
    ref and the output schema ref.  It is the only object that may attest
    that a dispatch physically completed and that the output is typed.
    """

    provider_session_id: str
    output_sha256: str
    observed_provider: str
    observed_model: str
    output_artifact_ref: str
    output_schema_ref: str

    def __post_init__(self) -> None:
        for name in ("provider_session_id", "observed_provider", "observed_model"):
            value = getattr(self, name)
            if not value or not value.strip():
                raise HarnessPolicyError(f"DispatchReceipt.{name} must be non-empty")
        sha = self.output_sha256.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise HarnessPolicyError(
                f"output_sha256 must be a 64-char hex digest: {self.output_sha256!r}"
            )
        object.__setattr__(self, "output_sha256", sha)
        # The output artifact ref must be a valid logical ref (same rule as
        # input artifacts) so the receipt carries typed artifact proof, not
        # just a bare hash.
        oar = self.output_artifact_ref.strip()
        if not oar:
            raise HarnessPolicyError(
                "DispatchReceipt.output_artifact_ref must be non-empty"
            )
        if not _ARTIFACT_REF_RE.fullmatch(oar) or _PATH_ESCAPE_RE.search(oar):
            raise HarnessPolicyError(
                f"DispatchReceipt.output_artifact_ref must be a closed logical id: "
                f"{self.output_artifact_ref!r}"
            )
        object.__setattr__(self, "output_artifact_ref", oar)
        osr = self.output_schema_ref.strip()
        if not osr:
            raise HarnessPolicyError(
                "DispatchReceipt.output_schema_ref must be non-empty"
            )
        object.__setattr__(self, "output_schema_ref", osr)


@dataclass(frozen=True)
class HarnessDispatchResult:
    """The harness's terminal classification of a dispatch attempt.

    ``receipt`` is set only on success.  ``error_code`` is a stable id
    describing a deterministic pre-dispatch rejection (``policy_*``),
    an adapter probe failure (``probe_failed``) or a workload-gate failure
    (``gate_*``).  The harness never fabricates a receipt and never classifies
    an ambiguous post-dispatch outcome as success.
    """

    success: bool
    receipt: DispatchReceipt | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class HarnessResult(HarnessDispatchResult):
    """The public harness result, carrying the adapter identity that produced it.

    ``dispatched`` is ``True`` only when the injected physical transport
    boundary was actually entered.  All pre-dispatch failures (policy, probe,
    gate, lease acquisition) report ``dispatched=False``.
    """

    adapter_identity: str | None = None
    dispatched: bool = False


@dataclass(frozen=True)
class FallbackInput:
    """The recorded evidence required to authorize a fallback dispatch.

    Fallback is never automatic.  The caller must present a terminal or
    unavailable result for the *same logical call* and the canonical source
    artifacts from which the minimal fallback input is rebuilt.  The previous
    provider's scratchpad, session transcript and raw sensitive payload are
    accepted purely so they can be proven discarded.
    """

    logical_call_id: str
    idempotency_key: str
    sensitivity_tier: SensitivityTier
    allowed_providers: tuple[str, ...]
    allowed_regions: tuple[str, ...]
    canonical_source: Mapping[str, Any]
    target_provider: str | None = None
    target_region: str | None = None
    previous_terminal_state: str = ""
    previous_error_code: str = ""
    previous_logical_call_id: str = ""
    previous_idempotency_key: str = ""
    previous_input_sha256: str = ""
    # Forbidden fragments — accepted only to be proven discarded.
    previous_provider_scratchpad: Mapping[str, Any] | None = None
    session_transcript: Sequence[Any] | None = None
    raw_sensitive_payload: Mapping[str, Any] | None = None


# ---------------------------------------------------------------------------
# Typed adapter outcome signal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdapterOutcome:
    """A small typed signal returned by an adapter's ``preflight`` check.

    Adapters use this to tell the dispatcher whether they are ready to accept
    a dispatch, and to report a stable error code + message when they are not.
    A ``None`` error code means the adapter is ready; a non-empty error code
    means the dispatch must be rejected *before* the physical transport
    boundary is entered (``dispatched=False``).
    """

    error_code: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_code is None


# ---------------------------------------------------------------------------
# Gate contract types (injected, never edited)
# ---------------------------------------------------------------------------

#: A gate selection mapping as reported by
#: :meth:`OmlxWorkloadGateClient.gate_selection`.  The harness reads only the
#: ``ocr`` and ``translation`` model identities from it; it never mutates the
#: gate or relabels its output.
GateSelection = Mapping[str, Any]

#: A gate lease context-manager factory.  The harness holds the correct
#: ``ocr``/``translation`` lease around the single transport call.  There is
#: no fake/no-op default — the factory must be injected for OCR/translation.
GateLeaseFactory = Any  # Callable producing a context manager


# ---------------------------------------------------------------------------
# Transport adapter protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class TransportAdapter(Protocol):
    """The injected transport surface the harness dispatches through.

    Adapters are deterministic, injected callables.  They MUST:

    * expose a stable :attr:`identity` (provider/model/harness triple) so the
      harness can cache a first-use connectivity probe per identity;
    * expose :attr:`provider`, :attr:`model` and :attr:`harness` for
      defence-in-depth routing checks;
    * implement :meth:`preflight` as a pure, side-effect-free check returning
      an :class:`AdapterOutcome` (``None`` error = ready; non-empty error =
      reject before transport);
    * implement :meth:`probe` as a cheap, side-effect-free connectivity check;
    * implement :meth:`dispatch` to accept a :class:`HarnessDispatchRequest`
      plus an optional ``session_id`` keyword and return a
      :class:`DispatchReceipt` on success, or raise on failure.

    The harness never calls ``dispatch`` before preflight + probe + gate +
    lease acquisition all succeed.
    """

    identity: str
    provider: str
    model: str
    harness: str

    def preflight(self, request: HarnessDispatchRequest) -> AdapterOutcome:
        """Return a ready outcome or a stable rejection error code.

        This is a pure check: it performs no side effects and never enters the
        physical transport boundary.  Identity/provider/model mismatches and
        unsupported-session rejections belong here so they report
        ``dispatched=False``.
        """
        ...

    def probe(self) -> bool:
        """Return ``True`` iff the adapter is reachable and correctly typed."""
        ...

    def dispatch(
        self,
        request: HarnessDispatchRequest,
        *,
        session_id: str | None = None,
        lease: Mapping[str, Any] | None = None,
    ) -> DispatchReceipt:
        """Physically dispatch *request* and return a typed receipt.

        ``lease`` carries the active workload-gate lease mapping for OCR/
        translation role kinds (acquired by the dispatcher); adapters that do
        not need it ignore it deterministically.
        """
        ...


@runtime_checkable
class Transport(Protocol):
    """Minimal callable transport for direct dispatch without an adapter class.

    This mirrors the Task 1.6 :class:`ExecutionTransport` shape: a plain
    callable that receives the policy-validated request and returns a receipt.
    Used when the harness dispatches directly (no coordinator).
    """

    def __call__(
        self,
        request: HarnessDispatchRequest,
        *,
        session_id: str | None = None,
    ) -> DispatchReceipt: ...


# ---------------------------------------------------------------------------
# Probe policy — cache only successful probes; never auto-retry failures
# ---------------------------------------------------------------------------


class ProbePolicy:
    """Per-identity first-use connectivity probe cache.

    A successful probe is cached so the adapter is not re-probed on every
    dispatch.  A failed probe is recorded as a negative result and never
    retried automatically — only :meth:`clear` (an explicit policy
    reconciliation action) removes a cached failure.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._probed_ok: set[str] = set()
        self._probed_failed: set[str] = set()

    def ensure_probed(self, adapter: TransportAdapter) -> None:
        """Probe *adapter* on first use; raise on failure.

        Raises :class:`AdapterProbeError` if the adapter's probe returns
        ``False`` or raises.  A cached success skips the probe; a cached
        failure re-raises without calling ``probe`` again.
        """
        identity = adapter.identity
        with self._lock:
            if identity in self._probed_ok:
                return
            if identity in self._probed_failed:
                raise AdapterProbeError(
                    f"adapter {identity!r} has a cached failed probe; "
                    "explicit policy reconciliation required"
                )
            # First-use probe.
            try:
                ok = adapter.probe()
            except Exception as exc:
                self._probed_failed.add(identity)
                raise AdapterProbeError(
                    f"adapter {identity!r} first-use probe raised: {type(exc).__name__}"
                ) from exc
            if not ok:
                self._probed_failed.add(identity)
                raise AdapterProbeError(
                    f"adapter {identity!r} first-use probe returned False"
                )
            self._probed_ok.add(identity)

    def clear(self, identity: str | None = None) -> None:
        """Clear cached probe state (explicit reconciliation only)."""
        with self._lock:
            if identity is None:
                self._probed_ok.clear()
                self._probed_failed.clear()
            else:
                self._probed_ok.discard(identity)
                self._probed_failed.discard(identity)


# ---------------------------------------------------------------------------
# Sensitivity tier ordering
# ---------------------------------------------------------------------------

#: Sensitivity tiers ranked from least to most sensitive.  The Role
#: target-profile sensitivity is the maximum permitted tier; a request whose
#: declared sensitivity is more sensitive than the role ceiling is rejected.
_SENSITIVITY_RANK: dict[SensitivityTier, int] = {
    SensitivityTier.PUBLIC: 0,
    SensitivityTier.INTERNAL: 1,
    SensitivityTier.CONFIDENTIAL: 2,
    SensitivityTier.RESTRICTED: 3,
}


# ---------------------------------------------------------------------------
# Policy validation
# ---------------------------------------------------------------------------

#: Role kinds that require the unified workload gate (effective model
#: selection + real lease) before dispatch.
_GATE_ROLE_KINDS = frozenset({"ocr", "translation"})


def _validate_role_binding(
    *,
    node_contract: NodeExecutionContract,
    role_entry: RoleEntry,
) -> None:
    """Validate that the node contract is bound to the exact registry role.

    Checks ``role_id`` equality, thinking discipline, target-profile
    provider/model/harness match, and that the contract effort is within the
    role's allowed efforts.  This replaces the caller-supplied boolean escape
    hatch: the immutable :class:`RoleEntry` is the sole thinking/effort
    authority.
    """
    if node_contract.role != role_entry.role_id:
        raise HarnessPolicyError(
            f"node_contract.role {node_contract.role!r} does not match "
            f"registered role_id {role_entry.role_id!r}"
        )

    target = role_entry.target_profile

    # Provider/model/harness must match the registered target profile exactly.
    if node_contract.provider != target.provider:
        raise HarnessPolicyError(
            f"provider {node_contract.provider!r} does not match role "
            f"target-profile provider {target.provider!r}"
        )
    if node_contract.model != target.model:
        raise HarnessPolicyError(
            f"model {node_contract.model!r} does not match role "
            f"target-profile model {target.model!r}"
        )
    if node_contract.harness != target.harness:
        raise HarnessPolicyError(
            f"harness {node_contract.harness!r} does not match role "
            f"target-profile harness {target.harness!r}"
        )

    # Thinking/effort discipline from the immutable registry role.
    effort_value = node_contract.reasoning_effort.value
    if effort_value not in role_entry.allowed_efforts:
        raise HarnessPolicyError(
            f"effort {effort_value!r} is not in role {role_entry.role_id!r} "
            f"allowed_efforts {list(role_entry.allowed_efforts)}"
        )
    if (
        not role_entry.thinking_configurable
        and effort_value != ReasoningEffort.NONE.value
    ):
        raise HarnessPolicyError(
            f"role {role_entry.role_id!r} is thinking-frozen but received "
            f"effort={effort_value!r}"
        )


def _validate_skill_binding(
    *,
    node_contract: NodeExecutionContract,
    skill: SkillDefinition,
) -> None:
    """Validate exact node↔skill binding: ids, schema refs, tools/paths subset."""
    if node_contract.skill_definition_id != skill.skill_definition_id:
        raise HarnessPolicyError(
            f"node_contract.skill_definition_id {node_contract.skill_definition_id!r} "
            f"does not match skill {skill.skill_definition_id!r}"
        )
    if node_contract.input_schema_ref != skill.input_schema_ref:
        raise HarnessPolicyError(
            f"node input_schema_ref {node_contract.input_schema_ref!r} does not "
            f"match skill {skill.input_schema_ref!r}"
        )
    if node_contract.output_schema_ref != skill.output_schema_ref:
        raise HarnessPolicyError(
            f"node output_schema_ref {node_contract.output_schema_ref!r} does not "
            f"match skill {skill.output_schema_ref!r}"
        )

    # Contract tools/paths are ALWAYS a subset of the skill's closed set, even
    # when the skill set is empty (an empty skill set means the contract may
    # not declare any tools/paths either).
    contract_tools = set(node_contract.allowed_tools)
    extra_tools = contract_tools - set(skill.allowed_tools)
    if extra_tools:
        raise HarnessPolicyError(
            f"node contract allows tools outside the skill's closed set: "
            f"{sorted(extra_tools)}"
        )
    contract_paths = set(node_contract.allowed_paths)
    extra_paths = contract_paths - set(skill.allowed_paths)
    if extra_paths:
        raise HarnessPolicyError(
            f"node contract allows paths outside the skill's closed set: "
            f"{sorted(extra_paths)}"
        )


def _validate_artifact_binding(
    *,
    node_contract: NodeExecutionContract,
    artifacts: Sequence[ArtifactRef],
) -> None:
    """Validate artifact-only input and exact versioned dependency binding.

    The exact passed artifact hash tuple (in order) must equal
    the legacy tuple or its v1.1 ordered digest. No substitution, omission,
    duplicate or reordering is permitted; compaction does not relax binding.
    """
    if not artifacts:
        raise HarnessPolicyError("at least one input artifact is required")
    refs = [a.ref for a in artifacts]
    if len(refs) != len(set(refs)):
        raise HarnessPolicyError("input artifact refs must be unique")
    # Exact ordered hash-tuple equality.
    passed_hashes = tuple(a.sha256 for a in artifacts)
    if not node_contract.matches_dependencies(passed_hashes):
        raise HarnessPolicyError(
            "artifact hash tuple does not match node_contract.input_artifact_hashes; "
            "input dependencies changed"
        )
    # Credential scan on bounded snippets.
    for artifact in artifacts:
        if artifact.snippet:
            _scan_credentials({"snippet": artifact.snippet}, "artifact")


def _validate_region_sensitivity(
    *,
    node_contract: NodeExecutionContract,
    role_entry: RoleEntry,
    selected_region: str,
) -> None:
    """Validate explicit selected region and sensitivity ceiling.

    The selected region must be in both the node allowlist and the Role
    target-profile regions.  The Role target-profile sensitivity tier is the
    maximum permitted tier; a more sensitive request is rejected.
    """
    region = selected_region.strip()
    if not region:
        raise HarnessPolicyError("an explicit selected target region is required")
    if region not in node_contract.allowed_regions:
        raise HarnessPolicyError(
            f"selected region {region!r} is outside the node contract "
            f"allowlist {list(node_contract.allowed_regions)}"
        )
    target = role_entry.target_profile
    if region not in target.regions:
        raise HarnessPolicyError(
            f"selected region {region!r} is outside the role target-profile "
            f"regions {list(target.regions)}"
        )

    # Provider allowlist (preserved).
    if node_contract.provider not in node_contract.allowed_providers:
        raise HarnessPolicyError(
            f"provider {node_contract.provider!r} is outside the contract "
            f"allowlist {list(node_contract.allowed_providers)}"
        )

    # Sensitivity ceiling: the role's target-profile tier is the max permitted.
    try:
        role_tier = SensitivityTier(target.sensitivity_tier)
    except ValueError as exc:
        raise HarnessPolicyError(
            f"role target-profile has unknown sensitivity_tier "
            f"{target.sensitivity_tier!r}"
        ) from exc
    request_rank = _SENSITIVITY_RANK.get(node_contract.sensitivity_tier)
    role_rank = _SENSITIVITY_RANK.get(role_tier)
    if request_rank is None or role_rank is None:
        raise HarnessPolicyError(
            f"unranked sensitivity tier: request={node_contract.sensitivity_tier!r} "
            f"role={role_tier!r}"
        )
    if request_rank > role_rank:
        raise HarnessPolicyError(
            f"request sensitivity {node_contract.sensitivity_tier.value!r} exceeds "
            f"the role target-profile ceiling {role_tier.value!r}"
        )


def _validated_request_kwargs(
    *,
    node_contract: NodeExecutionContract,
    skill: SkillDefinition,
    role_entry: RoleEntry,
    artifacts: Sequence[ArtifactRef],
    selected_region: str,
) -> dict[str, Any]:
    """Validate authoritative inputs and return canonical request fields.

    The returned fields are not dispatchable by themselves.  The public
    ``build_request`` retains the authoritative inputs as non-serialized
    evidence, and the dispatcher reruns this complete validator before every
    physical call.

    The immutable :class:`RoleEntry` (loaded by the strict registry loader) is
    the sole authority for role thinking/effort discipline, target
    provider/model/harness and sensitivity ceiling.  No caller-supplied
    boolean can override it.
    """
    # 1. Artifact-only input + exact hash binding + credential scan.
    _validate_artifact_binding(node_contract=node_contract, artifacts=artifacts)

    # 2. Exact node↔role binding (role_id, target profile, thinking/effort).
    _validate_role_binding(node_contract=node_contract, role_entry=role_entry)

    # 3. Exact node↔skill binding (ids, schema refs, tools/paths subset).
    _validate_skill_binding(node_contract=node_contract, skill=skill)

    # 4. Selected region + sensitivity ceiling.
    _validate_region_sensitivity(
        node_contract=node_contract,
        role_entry=role_entry,
        selected_region=selected_region,
    )

    if (
        node_contract.provider_session_id is not None
        and not node_contract.same_session_recovery
    ):
        raise HarnessPolicyError(
            "provider_session_id is present while same_session_recovery is false; "
            "the Harness refuses an undeclared provider-session resume"
        )

    return {
        "node_execution_contract_id": node_contract.node_execution_contract_id,
        "skill_definition_id": node_contract.skill_definition_id,
        "role": node_contract.role,
        "role_kind": role_entry.role_kind,
        "harness": node_contract.harness,
        "provider": node_contract.provider,
        "model": node_contract.model,
        "reasoning_effort": node_contract.reasoning_effort,
        "input_artifacts": tuple(artifacts),
        "input_schema_ref": skill.input_schema_ref,
        "output_schema_ref": skill.output_schema_ref,
        "allowed_tools": tuple(node_contract.allowed_tools),
        "allowed_paths": tuple(node_contract.allowed_paths),
        "sensitivity_tier": node_contract.sensitivity_tier,
        "selected_region": selected_region.strip(),
        "allowed_providers": tuple(node_contract.allowed_providers),
        "allowed_regions": tuple(node_contract.allowed_regions),
        "logical_call_id": node_contract.logical_call_id,
        "idempotency_key": node_contract.idempotency_key,
        "prompt_sha256": node_contract.prompt_sha256,
        "same_session_recovery": node_contract.same_session_recovery,
        "provider_session_id": node_contract.provider_session_id,
    }


def build_request(
    *,
    node_contract: NodeExecutionContract,
    skill: SkillDefinition,
    role_entry: RoleEntry,
    artifacts: Sequence[ArtifactRef],
    selected_region: str,
) -> HarnessDispatchRequest:
    """Build a request after validating all authoritative binding inputs."""
    artifact_tuple = tuple(artifacts)
    request = HarnessDispatchRequest(
        **_validated_request_kwargs(
            node_contract=node_contract,
            skill=skill,
            role_entry=role_entry,
            artifacts=artifact_tuple,
            selected_region=selected_region,
        )
    )
    object.__setattr__(
        request,
        "_binding_evidence",
        _RequestBindingEvidence(
            node_contract=node_contract,
            skill=skill,
            role_entry=role_entry,
            artifacts=artifact_tuple,
            selected_region=selected_region,
            node_contract_snapshot=_canonical_model_snapshot(node_contract),
            skill_snapshot=_canonical_model_snapshot(skill),
            role_entry_snapshot=_canonical_model_snapshot(role_entry),
            artifact_snapshot=_canonical_artifact_snapshot(artifact_tuple),
        ),
    )
    return request


def _request_matches_binding_evidence(request: HarnessDispatchRequest) -> bool:
    """Rerun complete binding validation and compare every dispatch field."""
    evidence = getattr(request, "_binding_evidence", None)
    if not isinstance(evidence, _RequestBindingEvidence):
        return False
    try:
        if (
            _canonical_model_snapshot(evidence.node_contract)
            != evidence.node_contract_snapshot
            or _canonical_model_snapshot(evidence.skill) != evidence.skill_snapshot
            or _canonical_model_snapshot(evidence.role_entry)
            != evidence.role_entry_snapshot
            or _canonical_artifact_snapshot(evidence.artifacts)
            != evidence.artifact_snapshot
        ):
            return False
        expected = HarnessDispatchRequest(
            **_validated_request_kwargs(
                node_contract=evidence.node_contract,
                skill=evidence.skill,
                role_entry=evidence.role_entry,
                artifacts=evidence.artifacts,
                selected_region=evidence.selected_region,
            )
        )
        return request.to_payload() == expected.to_payload()
    except Exception:  # noqa: BLE001 - any malformed retained evidence fails closed
        return False


def _canonical_model_snapshot(model: Any) -> str:
    """Return a complete deterministic snapshot of a frozen contract model."""
    return json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_artifact_snapshot(
    artifacts: Sequence[ArtifactRef],
) -> tuple[tuple[str, str, str], ...]:
    return tuple((item.ref, item.sha256, item.snippet) for item in artifacts)


# ---------------------------------------------------------------------------
# Unified workload-gate policy (common boundary, not adapter-local)
# ---------------------------------------------------------------------------


def _effective_gate_model(
    gate_selection: GateSelection,
    role_kind: str,
) -> str:
    """Return the effective model id for *role_kind* from the gate selection.

    Reads ``models.<role_kind>`` or a flat ``<role_kind>`` key defensively.
    Returns ``""`` when no selection is reported.
    """
    models = gate_selection.get("models")
    if isinstance(models, Mapping):
        value = models.get(role_kind)
        if isinstance(value, str) and value.strip():
            return value
    value = gate_selection.get(role_kind)
    if isinstance(value, str) and value.strip():
        return value
    return ""


def _ensure_gate_consistency(
    *,
    request: HarnessDispatchRequest,
    gate_selection: GateSelection | None,
    lease_factory: GateLeaseFactory | None,
) -> None:
    """Enforce the unified workload-gate policy for OCR/translation roles.

    For role kinds ``ocr`` and ``translation``:

    * an injected read-only effective model selection is required;
    * a real injected lease context factory is required (no fake/no-op
      default);
    * the declared model must match the effective model exactly;
    * a missing or mismatched selection fails closed before probe/dispatch.

    This applies to Paddle Direct API and local oMLX equally.  The current
    ``GLM-OCR-bf16`` vs Paddle mismatch remains a deterministic pre-dispatch
    failure; translation succeeds only when the effective Hy-MT2 identity
    matches.
    """
    if request.role_kind not in _GATE_ROLE_KINDS:
        return

    if gate_selection is None:
        raise WorkloadGateError(
            f"role_kind {request.role_kind!r} requires an injected effective "
            "gate model selection; none was provided"
        )
    if lease_factory is None:
        raise WorkloadGateError(
            f"role_kind {request.role_kind!r} requires an injected real lease "
            "context factory; no fake/no-op default is permitted"
        )

    effective = _effective_gate_model(gate_selection, request.role_kind)
    if not effective:
        raise WorkloadGateError(
            f"role_kind {request.role_kind!r}: the gate reports no effective "
            f"model selection; declared model {request.model!r} cannot be "
            "reconciled before invocation"
        )
    if effective != request.model:
        raise WorkloadGateError(
            f"role_kind {request.role_kind!r}: declared model {request.model!r} "
            f"does not match the effective gate model {effective!r}. "
            "No output may be relabeled. Reconcile the gate policy before live use."
        )


def _lease_kind_for_role_kind(role_kind: str) -> str:
    """Map a role kind to the gate workload bucket (``ocr``/``translation``)."""
    if role_kind == "ocr":
        return "ocr"
    return "translation"


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------


def build_fallback_request(fallback: FallbackInput) -> dict[str, Any]:
    """Build a minimal, safe fallback payload from canonical artifact refs.

    Fallback is never automatic.  The caller must present:

    * a recorded terminal/unavailable result for the same logical call
      (``previous_terminal_state`` / ``previous_error_code``);
    * the canonical source artifacts from which the minimal input is rebuilt.

    The previous provider's scratchpad, session transcript and raw sensitive
    payload are accepted purely so the audit trail can prove they were known
    and intentionally discarded — they are never copied into the returned
    payload.  When the sensitivity policy cannot be satisfied, this fails
    closed with :class:`HarnessFallbackError` (wrapping
    :class:`FallbackSafetyViolation`).
    """
    eligible_states = {"failed", "unknown_outcome", "unavailable"}
    terminal = fallback.previous_terminal_state.strip().lower()
    if terminal not in eligible_states:
        raise HarnessFallbackError(
            "fallback requires a recorded eligible terminal/unavailable result "
            f"(one of {sorted(eligible_states)}); got {terminal!r}"
        )
    if not fallback.previous_error_code.strip():
        raise HarnessFallbackError(
            "fallback requires a recorded error code for the previous result"
        )

    logical_call_id = fallback.logical_call_id.strip()
    idempotency_key = fallback.idempotency_key.strip()
    if not logical_call_id or not idempotency_key:
        raise HarnessFallbackError(
            "fallback requires non-empty logical_call_id and idempotency_key"
        )
    if fallback.previous_logical_call_id.strip() != logical_call_id:
        raise HarnessFallbackError(
            "fallback prior evidence does not match logical_call_id"
        )
    if fallback.previous_idempotency_key.strip() != idempotency_key:
        raise HarnessFallbackError(
            "fallback prior evidence does not match idempotency_key"
        )
    expected_input_sha256 = canonical_input_hash(
        logical_call_id=logical_call_id,
        idempotency_key=idempotency_key,
        payload=fallback.canonical_source,
    )
    if fallback.previous_input_sha256 != expected_input_sha256:
        raise HarnessFallbackError(
            "fallback prior evidence input hash does not match canonical source"
        )

    try:
        rebuilt = rebuild_fallback_payload(
            canonical_source=fallback.canonical_source,
            sensitivity_tier=fallback.sensitivity_tier,
            allowed_providers=fallback.allowed_providers,
            allowed_regions=fallback.allowed_regions,
            previous_provider_scratchpad=fallback.previous_provider_scratchpad,
            session_transcript=fallback.session_transcript,
            raw_sensitive_payload=fallback.raw_sensitive_payload,
            target_provider=fallback.target_provider,
            target_region=fallback.target_region,
        )
    except FallbackSafetyViolation as exc:
        raise HarnessFallbackError(str(exc)) from exc

    # Credential-scan the rebuilt payload as defence-in-depth.
    _scan_credentials(rebuilt, "fallback_payload")
    return rebuilt


# ---------------------------------------------------------------------------
# Harness dispatcher
# ---------------------------------------------------------------------------


@dataclass
class HarnessDispatcher:
    """The stateful harness dispatcher.

    Holds a :class:`ProbePolicy` (first-use probe cache) and dispatches
    policy-validated requests through an injected :class:`TransportAdapter`.
    The dispatcher is deterministic: given the same adapter and request it
    produces the same outcome, and it never dispatches before policy + gate +
    lease + probe + preflight validation.

    For OCR/translation role kinds the dispatcher requires an injected
    ``gate_selection`` and ``lease_factory`` so the unified workload-gate
    policy is enforced at the common boundary, not inside individual adapters.
    """

    probe_policy: ProbePolicy = field(default_factory=ProbePolicy)

    def dispatch(
        self,
        *,
        request: HarnessDispatchRequest,
        adapter: TransportAdapter,
        gate_selection: GateSelection | None = None,
        lease_factory: GateLeaseFactory | None = None,
    ) -> HarnessResult:
        """Validate, probe, gate, lease then dispatch *request* through *adapter*.

        Returns a :class:`HarnessResult` describing the outcome.  Every
        pre-dispatch failure (policy, probe, gate, lease acquisition, adapter
        preflight) returns a failed result with ``dispatched=False`` and zero
        transport calls.  ``dispatched=True`` is set only when the injected
        physical transport boundary is actually entered.

        ``session_id`` is forwarded from ``request.provider_session_id`` so
        same-session recovery travels into the adapter without forcing callers
        to bypass probe/policy.
        """
        identity = adapter.identity

        # 0. Session polarity is an explicit invariant and retains its stable
        #    error even when a caller has altered an otherwise validated request.
        if (
            request.provider_session_id is not None
            and not request.same_session_recovery
        ):
            return HarnessResult(
                success=False,
                error_code="session_recovery_not_authorized",
                error_message=(
                    "provider_session_id is present while same_session_recovery "
                    "is false"
                ),
                adapter_identity=identity,
                dispatched=False,
            )

        # 1. Rerun the complete authoritative binding validation and compare
        #    every rebuilt dispatch field.  Direct, copied or subsequently
        #    altered requests fail before gate/preflight/probe.
        if not _request_matches_binding_evidence(request):
            return HarnessResult(
                success=False,
                error_code="request_unvalidated",
                error_message=(
                    "HarnessDispatchRequest does not match revalidated binding "
                    "evidence (RoleEntry/Skill/artifact/region/session)"
                ),
                adapter_identity=identity,
                dispatched=False,
            )
        adapter_harness = getattr(adapter, "harness", None)
        if adapter_harness != request.harness:
            return HarnessResult(
                success=False,
                error_code="adapter_harness_mismatch",
                error_message=(
                    f"adapter harness {adapter_harness!r} does not match "
                    f"request harness {request.harness!r}"
                ),
                adapter_identity=identity,
                dispatched=False,
            )
        # 1. Unified workload-gate policy (before probe).  For OCR/translation
        #    role kinds this compares the declared model to the effective gate
        #    model and requires a real lease factory.
        try:
            _ensure_gate_consistency(
                request=request,
                gate_selection=gate_selection,
                lease_factory=lease_factory,
            )
        except WorkloadGateError as exc:
            return HarnessResult(
                success=False,
                error_code="gate_policy_violation",
                error_message=str(exc),
                adapter_identity=identity,
                dispatched=False,
            )

        # 2. Adapter preflight (pure, before probe).  Identity/provider/model
        #    mismatches and unsupported-session rejections report
        #    ``dispatched=False``.  A missing or non-callable preflight is a
        #    contract violation, not a bypass: it fails closed with zero probe
        #    and zero transport calls.
        preflight_fn = getattr(adapter, "preflight", None)
        if not callable(preflight_fn):
            return HarnessResult(
                success=False,
                error_code="preflight_missing",
                error_message=(
                    f"adapter {identity!r} does not expose a callable preflight; "
                    "every adapter must implement preflight(request) -> AdapterOutcome"
                ),
                adapter_identity=identity,
                dispatched=False,
            )
        try:
            preflight = preflight_fn(request)
        except Exception as exc:  # noqa: BLE001
            return HarnessResult(
                success=False,
                error_code="preflight_exception",
                error_message=f"{type(exc).__name__}: {exc}",
                adapter_identity=identity,
                dispatched=False,
            )
        if not isinstance(preflight, AdapterOutcome):
            return HarnessResult(
                success=False,
                error_code="preflight_invalid_result",
                error_message=(
                    f"adapter {identity!r} preflight returned "
                    f"{type(preflight).__name__}, not AdapterOutcome"
                ),
                adapter_identity=identity,
                dispatched=False,
            )
        if not preflight.ok:
            return HarnessResult(
                success=False,
                error_code=preflight.error_code or "preflight_rejected",
                error_message=preflight.error_message or "adapter preflight rejected",
                adapter_identity=identity,
                dispatched=False,
            )

        # 3. Probe-once-per-identity.
        try:
            self.probe_policy.ensure_probed(adapter)
        except AdapterProbeError as exc:
            return HarnessResult(
                success=False,
                error_code="probe_failed",
                error_message=str(exc),
                adapter_identity=identity,
                dispatched=False,
            )

        # 4. Credential scan the final payload immediately before dispatch.
        payload = request.to_payload()
        try:
            _scan_credentials(payload, "dispatch_payload")
        except HarnessPolicyError as exc:
            return HarnessResult(
                success=False,
                error_code="policy_credential_detected",
                error_message=str(exc),
                adapter_identity=identity,
                dispatched=False,
            )

        # 5. Output schema control metadata — validated against the receipt
        #    after dispatch.

        # 6. Acquire the workload-gate lease for OCR/translation roles and
        #    hold it around the single transport call.  For non-gate roles
        #    dispatch proceeds without a lease.
        session_id = request.provider_session_id

        if request.role_kind in _GATE_ROLE_KINDS:
            return self._dispatch_gated(
                request=request,
                adapter=adapter,
                identity=identity,
                lease_factory=lease_factory,
                session_id=session_id,
                expected_output_schema=request.output_schema_ref,
                expected_provider=request.provider,
                expected_model=request.model,
            )

        # Non-gated dispatch (LLM, ocr_translation_support).
        return self._dispatch_direct(
            request=request,
            adapter=adapter,
            identity=identity,
            session_id=session_id,
            expected_output_schema=request.output_schema_ref,
            expected_provider=request.provider,
            expected_model=request.model,
        )

    # ------------------------------------------------------------------
    # Internal dispatch paths
    # ------------------------------------------------------------------

    def _dispatch_direct(
        self,
        *,
        request: HarnessDispatchRequest,
        adapter: TransportAdapter,
        identity: str,
        session_id: str | None,
        expected_output_schema: str,
        expected_provider: str,
        expected_model: str,
    ) -> HarnessResult:
        """Dispatch without a workload-gate lease (LLM / support roles)."""
        try:
            receipt = adapter.dispatch(request, session_id=session_id)
        except Exception as exc:  # noqa: BLE001
            return HarnessResult(
                success=False,
                error_code="dispatch_exception",
                error_message=f"{type(exc).__name__}: {exc}",
                adapter_identity=identity,
                dispatched=True,
            )
        return self._validate_receipt(
            receipt=receipt,
            identity=identity,
            expected_output_schema=expected_output_schema,
            expected_provider=expected_provider,
            expected_model=expected_model,
        )

    def _dispatch_gated(
        self,
        *,
        request: HarnessDispatchRequest,
        adapter: TransportAdapter,
        identity: str,
        lease_factory: GateLeaseFactory,
        session_id: str | None,
        expected_output_schema: str,
        expected_provider: str,
        expected_model: str,
    ) -> HarnessResult:
        """Dispatch under a workload-gate lease (OCR / translation roles).

        The correct ``ocr``/``translation`` lease is acquired before the
        single transport call and released in a ``finally``.  A lease
        acquisition failure reports ``dispatched=False`` because the physical
        transport boundary was never entered.
        """
        kind = _lease_kind_for_role_kind(request.role_kind)
        owner = f"harness:{request.logical_call_id}"

        # Acquire the lease.  If acquisition fails, we never entered the
        # transport boundary.
        try:
            lease_cm = lease_factory(kind=kind, owner=owner)
            lease = _enter_context(lease_cm)
        except Exception as exc:  # noqa: BLE001
            return HarnessResult(
                success=False,
                error_code="gate_lease_acquisition_failed",
                error_message=f"{type(exc).__name__}: {exc}",
                adapter_identity=identity,
                dispatched=False,
            )

        try:
            receipt = adapter.dispatch(request, session_id=session_id, lease=lease)
        except Exception as dispatch_exc:  # noqa: BLE001
            try:
                lease_cm.__exit__(
                    type(dispatch_exc), dispatch_exc, dispatch_exc.__traceback__
                )
            except Exception as release_exc:  # noqa: BLE001
                return HarnessResult(
                    success=False,
                    error_code="dispatch_exception",
                    error_message=(
                        f"{type(dispatch_exc).__name__}: {dispatch_exc}; "
                        "workload lease release also failed: "
                        f"{type(release_exc).__name__}: {release_exc}"
                    ),
                    adapter_identity=identity,
                    dispatched=True,
                )
            return HarnessResult(
                success=False,
                error_code="dispatch_exception",
                error_message=f"{type(dispatch_exc).__name__}: {dispatch_exc}",
                adapter_identity=identity,
                dispatched=True,
            )

        try:
            lease_cm.__exit__(None, None, None)
        except Exception as release_exc:  # noqa: BLE001
            return HarnessResult(
                success=False,
                error_code="gate_lease_release_failed",
                error_message=f"{type(release_exc).__name__}: {release_exc}",
                adapter_identity=identity,
                dispatched=True,
            )

        return self._validate_receipt(
            receipt=receipt,
            identity=identity,
            expected_output_schema=expected_output_schema,
            expected_provider=expected_provider,
            expected_model=expected_model,
        )

    def _validate_receipt(
        self,
        *,
        receipt: DispatchReceipt,
        identity: str,
        expected_output_schema: str,
        expected_provider: str,
        expected_model: str,
    ) -> HarnessResult:
        """Validate the typed receipt: schema equality and observed identity.

        The receipt is runtime authority, so its explicit observed
        provider/model must match the validated request.  A mismatch is a
        stable typed failure (``receipt_identity_mismatch``) with
        ``dispatched=True`` — the transport boundary was entered but the
        returned identity is wrong.
        """
        if not isinstance(receipt, DispatchReceipt):
            return HarnessResult(
                success=False,
                error_code="dispatch_invalid_receipt",
                error_message=(
                    f"adapter returned {type(receipt).__name__}, not DispatchReceipt"
                ),
                adapter_identity=identity,
                dispatched=True,
            )
        if receipt.output_schema_ref != expected_output_schema:
            return HarnessResult(
                success=False,
                error_code="receipt_schema_mismatch",
                error_message=(
                    f"receipt output_schema_ref {receipt.output_schema_ref!r} does not "
                    f"match request output schema {expected_output_schema!r}"
                ),
                adapter_identity=identity,
                dispatched=True,
            )
        if receipt.observed_provider != expected_provider:
            return HarnessResult(
                success=False,
                error_code="receipt_identity_mismatch",
                error_message=(
                    f"receipt observed_provider {receipt.observed_provider!r} does not "
                    f"match request provider {expected_provider!r}"
                ),
                adapter_identity=identity,
                dispatched=True,
            )
        if receipt.observed_model != expected_model:
            return HarnessResult(
                success=False,
                error_code="receipt_identity_mismatch",
                error_message=(
                    f"receipt observed_model {receipt.observed_model!r} does not "
                    f"match request model {expected_model!r}"
                ),
                adapter_identity=identity,
                dispatched=True,
            )
        return HarnessResult(
            success=True,
            receipt=receipt,
            adapter_identity=identity,
            dispatched=True,
        )


# ---------------------------------------------------------------------------
# Context-manager helpers (typed lease lifecycle without try/except guessing)
# ---------------------------------------------------------------------------


def _enter_context(cm: Any) -> Any:
    """Enter a context manager and return its yielded value."""
    return cm.__enter__()


# ---------------------------------------------------------------------------
# Re-exports for tests and audit
# ---------------------------------------------------------------------------

# Re-export the credential scanners and logical-ref patterns for tests/audit.
__all__.extend(
    [
        "_ARTIFACT_REF_RE",
        "_CREDENTIAL_KEY_RE",
        "_CREDENTIAL_VALUE_RE",
        "_PATH_ESCAPE_RE",
        "WorkloadGateError",
    ]
)

# Backwards-compatible alias used by adapters/tests.
HarnessAdapter = TransportAdapter
