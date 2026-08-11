"""Canonical input identity, logical-work keying and safe fallback repackaging.

This module is part of the Protocol v3 ExecutionReservation runtime (frozen
plan Task 1.6).  It provides three deterministic, side-effect-free helpers
used by the reservation coordinator (``runtime.reservations``):

* :func:`canonical_input_hash` — the stable content hash that identifies
  whether a request carries the same logical work as a previous reservation.
  It is deliberately invariant to runtime metadata (timestamps, attempt
  counters, dispatch ids) so that a materially-identical request is never
  misclassified as stale and therefore never accidentally redispatched.

* :func:`logical_work_key` — the deterministic identity string for a logical
  call scoped by its idempotency key.  Two reservations with the same logical
  work key and the same canonical input hash are the same unit of work.

* :func:`rebuild_fallback_payload` — rebuilds a minimal dispatch payload from
  the canonical source for a cross-provider fallback, explicitly stripping the
  previous provider's scratchpad, session transcript and any raw sensitive
  payload that must not travel to the next provider.  When the safety policy
  cannot be satisfied (the canonical source itself carries a sensitivity tier
  the target provider/region is not authorised to receive) it fails closed
  with :class:`FallbackSafetyViolation`.

Design authority: ``plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md``
sections 17.2 and 18:

    跨 provider fallback 必须从 canonical source 重新执行数据分级、
    provider/region allowlist 和最小打包，禁止把上一会话、scratchpad 或
    原始敏感 payload 原样转交下一 provider；策略不允许时 fail closed。

    harness fallback 先查询同一 logical work key 的已验证 artifact；除非前一
    artifact 完整性失败，不得为了换 provider/model 重做已完成副作用。

The helpers are pure: they perform no repository, filesystem, network, clock
or model access.  They reuse the canonical JSON discipline established in
``app.protocol_workflow.canonical.hashing`` so that the same logical input
always produces the same identity regardless of where or when the coordinator
runs.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping, Sequence

from packages.contracts.workbench_contracts.protocol_v3 import (
    SensitivityTier,
)

from app.protocol_workflow.canonical.hashing import canonical_json

__all__ = [
    "FallbackSafetyViolation",
    "canonical_input_hash",
    "logical_work_key",
    "rebuild_fallback_payload",
]


# ---------------------------------------------------------------------------
# Metadata stripping
# ---------------------------------------------------------------------------

#: Payload keys that are pure runtime metadata: timestamps, attempt counters,
#: dispatch ids and other harness bookkeeping.  These must never change the
#: canonical input hash, because they are not material content — they describe
#: *when* and *how many times* a request was issued, not *what* it asks for.
#:
#: The underscore prefix is the harness convention for injected runtime
#: metadata (see ``NodeExecutionContract`` and the legacy prefill reservation).
#: The named model metadata fields (``updated_at``, ``revision`` …) are already
#: handled by the ``ProtocolV3Model.material_metadata_fields`` discipline; the
#: underscore-prefixed set below covers the runtime-injected payload keys that
#: never participate in the reservation identity.
_RUNTIME_METADATA_PREFIX = "_"


def _strip_runtime_metadata(value: Any) -> Any:
    """Recursively remove runtime-metadata keys from *value*.

    Only mappings are filtered; sequences are traversed element-wise.  A key is
    runtime metadata when it starts with the harness underscore convention
    (``_timestamp``, ``_attempt``, ``_dispatch_id`` …).  Legitimate content keys
    that happen to start with an underscore are not part of the Protocol v3
    contract surface and are therefore treated as harness metadata by design.
    """
    if isinstance(value, Mapping):
        return {
            key: _strip_runtime_metadata(item)
            for key, item in value.items()
            if not (isinstance(key, str) and key.startswith(_RUNTIME_METADATA_PREFIX))
        }
    if isinstance(value, (list, tuple)):
        return [_strip_runtime_metadata(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------


def logical_work_key(
    *,
    logical_call_id: str,
    idempotency_key: str,
) -> str:
    """Return the deterministic identity string for a logical call.

    The logical work key scopes the idempotency space: two reservations share
    the same logical work key if and only if they address the same logical
    call with the same idempotency key.  The canonical input hash then
    decides whether they carry the same material content.

    The returned string is stable, printable and embeds both components so it
    can be used as a repository index prefix or audit label without ambiguity.
    """
    identity = {
        "logical_call_id": logical_call_id,
        "idempotency_key": idempotency_key,
    }
    return canonical_json(identity)


def canonical_input_hash(
    *,
    logical_call_id: str,
    idempotency_key: str,
    payload: Mapping[str, Any],
) -> str:
    """Return the stable content hash for a reservation request.

    The hash binds the logical call id and *material* payload content.  The
    idempotency key scopes the repository lookup but is deliberately excluded
    from the material digest, so an explicit retry decision does not make
    unchanged clinical input appear different.  Runtime metadata is
    stripped before hashing so that a retried or re-issued request carrying
    identical material content produces the identical hash and is therefore
    recognised as a completed-result reuse rather than a stale redispatch.

    The encoding is order-independent (keys are sorted recursively via
    :func:`canonical_json`) so two semantically identical payloads with
    different insertion order hash to the same digest.
    """
    del idempotency_key
    stripped = _strip_runtime_metadata(dict(payload))
    identity = {
        "logical_call_id": logical_call_id,
        "payload": stripped,
    }
    return sha256(canonical_json(identity).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cross-provider fallback re-packaging
# ---------------------------------------------------------------------------

#: Forbidden payload fragments that must never travel to the next provider on a
#: cross-provider fallback.  Each is named explicitly so the audit trail can
#: explain *what* was stripped.
_FORBIDDEN_FALLBACK_FRAGMENTS = (
    "previous_provider_scratchpad",
    "session_transcript",
    "raw_sensitive_payload",
)


class FallbackSafetyViolation(RuntimeError):
    """Raised when a cross-provider fallback cannot be made safe.

    The canonical source carries material that the target provider/region is
    not authorised to receive, and the forbidden fragments cannot be excluded
    without losing the canonical content itself.  Per design section 17.2 the
    re-builder fails closed rather than forwarding unsafe material.
    """


def rebuild_fallback_payload(
    *,
    canonical_source: Mapping[str, Any],
    sensitivity_tier: SensitivityTier,
    allowed_providers: Sequence[str],
    allowed_regions: Sequence[str],
    previous_provider_scratchpad: Mapping[str, Any] | None = None,
    session_transcript: Sequence[Any] | None = None,
    raw_sensitive_payload: Mapping[str, Any] | None = None,
    target_provider: str | None = None,
    target_region: str | None = None,
) -> dict[str, Any]:
    """Rebuild a minimal dispatch payload for a cross-provider fallback.

    The rebuilt payload contains *only* the canonical source material.  The
    previous provider's scratchpad, the session transcript and any raw
    sensitive payload are explicitly never forwarded — they are accepted as
    parameters purely so the caller can prove (and the audit trail can show)
    that the fragments were known and intentionally discarded.

    The sensitivity policy is enforced before the payload is returned:

    * ``PUBLIC`` / ``INTERNAL`` content may be forwarded to any authorised
      provider/region.
    * ``CONFIDENTIAL`` content requires at least one allowed provider and one
      allowed region to be declared.
    * ``RESTRICTED`` content requires the target provider/region to be present
      in the allowlist; if no target is declared or the target is outside the
      allowlist, the re-builder fails closed with
      :class:`FallbackSafetyViolation`.

    Parameters
    ----------
    canonical_source:
        The canonical source material for the logical call.  Only this
        material is forwarded; it is copied defensively so the caller cannot
        observe mutation of the returned payload.
    sensitivity_tier:
        The sensitivity tier of the canonical source, as declared on the
        ``NodeExecutionContract``.
    allowed_providers / allowed_regions:
        The provider/region allowlist the target must satisfy.  These mirror
        the contract fields and exist so the re-builder is self-contained and
        auditable.
    previous_provider_scratchpad / session_transcript / raw_sensitive_payload:
        Forbidden fragments.  Accepted so the caller can prove they were known
        and discarded; never copied into the returned payload.
    target_provider / target_region:
        Optional explicit target for the fallback.  ``RESTRICTED`` material
        requires both values so the runtime never delegates the final target
        choice to an implicit caller default.

    Returns
    -------
    dict[str, Any]
        The minimal, safe dispatch payload containing only the canonical
        source material.

    Raises
    ------
    FallbackSafetyViolation
        When the canonical source sensitivity cannot be satisfied by the
        target provider/region, or when a forbidden fragment is detected
        inside the canonical source itself (the source was contaminated).
    """
    # --- 1. Reject forbidden fragments that somehow reached the source ----
    # If the canonical source itself is contaminated with a fragment named
    # like a forbidden payload, fail closed: we cannot safely extract it.
    contaminated = _find_forbidden_fragments(canonical_source)
    if contaminated:
        raise FallbackSafetyViolation(
            "canonical source is contaminated with forbidden fallback "
            f"fragment(s): {sorted(contaminated)}"
        )

    # --- 2. Enforce the sensitivity / provider / region policy ------------
    _enforce_safety_policy(
        sensitivity_tier=sensitivity_tier,
        allowed_providers=tuple(allowed_providers),
        allowed_regions=tuple(allowed_regions),
        target_provider=target_provider,
        target_region=target_region,
    )

    # --- 3. Rebuild the minimal payload from canonical source only --------
    # The forbidden fragments are deliberately not copied.  We deep-copy the
    # canonical source so the returned payload is independently mutable and
    # the caller cannot observe mutation of the original mapping.
    rebuilt: dict[str, Any] = {}
    for key, value in canonical_source.items():
        rebuilt[key] = _deep_copy_value(value)
    return rebuilt


def _enforce_safety_policy(
    *,
    sensitivity_tier: SensitivityTier,
    allowed_providers: tuple[str, ...],
    allowed_regions: tuple[str, ...],
    target_provider: str | None,
    target_region: str | None,
) -> None:
    """Enforce the provider/region/sensitivity allowlist for a fallback.

    Raises :class:`FallbackSafetyViolation` when the target is outside the
    allowlist for the canonical source's sensitivity tier, or when the
    allowlist is too weak to receive the declared sensitivity.

    Provider and region names are opaque identifiers.  Authorization comes
    only from the explicit allowlists and explicit target, never from tokens
    heuristically embedded in a provider or region name.
    """
    # An empty allowlist is never safe for any non-public content.
    if not allowed_providers or not allowed_regions:
        if sensitivity_tier is SensitivityTier.PUBLIC:
            return
        raise FallbackSafetyViolation(
            "cross-provider fallback requires a non-empty provider/region "
            f"allowlist for {sensitivity_tier.value} content"
        )

    if sensitivity_tier is SensitivityTier.RESTRICTED and (
        target_provider is None or target_region is None
    ):
        raise FallbackSafetyViolation(
            "restricted content requires an explicit target provider and region"
        )

    _reject_explicit_target_outside_allowlist(
        target_provider=target_provider,
        target_region=target_region,
        allowed_providers=allowed_providers,
        allowed_regions=allowed_regions,
    )


def _reject_explicit_target_outside_allowlist(
    *,
    target_provider: str | None,
    target_region: str | None,
    allowed_providers: tuple[str, ...],
    allowed_regions: tuple[str, ...],
) -> None:
    """Reject an explicit target that is outside the declared allowlist."""
    if target_provider is not None and target_provider not in allowed_providers:
        raise FallbackSafetyViolation(
            f"target provider '{target_provider}' is outside the "
            f"allowlist: {list(allowed_providers)}"
        )
    if target_region is not None and target_region not in allowed_regions:
        raise FallbackSafetyViolation(
            f"target region '{target_region}' is outside the "
            f"allowlist: {list(allowed_regions)}"
        )


def _find_forbidden_fragments(value: Any) -> set[str]:
    """Return forbidden fragment keys found anywhere in canonical content."""
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _FORBIDDEN_FALLBACK_FRAGMENTS:
                found.add(key)
            found.update(_find_forbidden_fragments(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(_find_forbidden_fragments(item))
    return found


def _deep_copy_value(value: Any) -> Any:
    """Deep-copy a JSON-compatible value defensively.

    Mappings are copied as ``dict``, sequences as ``list``; scalars are
    returned as-is.  This keeps the rebuilt payload independent of the
    caller's canonical source mapping.
    """
    if isinstance(value, Mapping):
        return {key: _deep_copy_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_copy_value(item) for item in value]
    return value
