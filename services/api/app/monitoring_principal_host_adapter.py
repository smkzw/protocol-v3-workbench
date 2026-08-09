"""Host seam for a server-verified monitoring principal.

The workbench host may eventually install an authentication/session middleware
that places a verified :class:`MonitoringAuthenticatedPrincipal` on
``request.state``.  This adapter only reads that already-verified object.  It
does not parse headers, cookies, bearer tokens, client actors, or session
material, and it returns ``None`` for missing or malformed state so the route
boundary can fail closed.
"""

from __future__ import annotations

from fastapi import Request

from .monitoring_runtime_principal import MonitoringAuthenticatedPrincipal


MONITORING_PRINCIPAL_STATE_KEY = "monitoring_principal"


def resolve_monitoring_principal_from_request(
    request: Request,
) -> MonitoringAuthenticatedPrincipal | None:
    """Read the host-provided verified principal without authenticating it."""

    candidate = getattr(request.state, MONITORING_PRINCIPAL_STATE_KEY, None)
    if isinstance(candidate, MonitoringAuthenticatedPrincipal):
        return candidate
    return None
