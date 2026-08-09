"""Offline identity and action-authorization contract for medical monitoring.

The first local release may use one explicitly identified medical-manager
principal, but it must not hide that simplification behind a default actor.
This module records the target deployment roles, action boundaries and project
scope in an immutable, hashable decision.  It does not authenticate a user,
persist an audit event, issue an electronic signature or authorize a router
write; those integrations remain controlled deployment work.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Literal


MONITORING_AUTHORIZATION_SCHEMA_VERSION = "monitoring_identity_authorization_v1"
MonitoringScopeType = Literal["trial", "site", "subject"]
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class MonitoringRole(str, Enum):
    MEDICAL_MONITOR = "medical_monitor"
    MEDICAL_MANAGER = "medical_manager"
    MEDICAL_DIRECTOR = "medical_director"
    MEDICAL_WRITER = "medical_writer"
    CLINICAL_OPERATIONS = "clinical_operations"
    DATA_MANAGEMENT = "data_management"
    PV = "pv"
    STATISTICS_PROGRAMMING = "statistics_programming"
    SYSTEM_ADMIN = "system_admin"
    PRODUCT_ENGINEERING = "product_engineering"


class MonitoringAction(str, Enum):
    READ_MONITORING = "read_monitoring"
    # Surface-specific reads are intentionally separate from the historical
    # aggregate action.  They are not wired to legacy HTTP routes yet; a
    # future route must opt into the exact action and its module contract.
    READ_DASHBOARD = "read_dashboard"
    READ_WORKBENCH_INBOX = "read_workbench_inbox"
    READ_AI_RUN = "read_ai_run"
    READ_AI_ARTIFACT = "read_ai_artifact"
    READ_SOURCE_EVIDENCE = "read_source_evidence"
    READ_RISK_AUDIT = "read_risk_audit"
    READ_RUNTIME_AUDIT = "read_runtime_audit"
    INTAKE_BATCH = "intake_batch"
    RUN_DETERMINISTIC_RULES = "run_deterministic_rules"
    REVIEW_AI_CANDIDATE = "review_ai_candidate"
    CHANGE_RISK_DISPOSITION = "change_risk_disposition"
    DRAFT_QUERY = "draft_query"
    CREATE_ASSURANCE_TASK = "create_assurance_task"
    RECORD_ASSURANCE_EVIDENCE = "record_assurance_evidence"
    REVIEW_ASSURANCE = "review_assurance"
    EXPORT_RISK_EVIDENCE = "export_risk_evidence"
    COMPLETE_ASSURANCE = "complete_assurance"
    CONFIRM_HIGH_RISK_CLOSE = "confirm_high_risk_close"
    APPROVE_RULE_CHANGE = "approve_rule_change"
    PROVIDE_CENTER_CONTEXT = "provide_center_context"
    VALIDATE_SOURCE_REVISION = "validate_source_revision"
    MARK_SAFETY_PV_REVIEW = "mark_safety_pv_review"
    CONFIRM_DERIVED_DATA = "confirm_derived_data"
    ADMINISTER_RUNTIME = "administer_runtime"


class MonitoringAuthorizationReason(str, Enum):
    AUTHORIZED = "authorized"
    AUTHENTICATION_REQUIRED = "authentication_required"
    PRINCIPAL_MISMATCH = "principal_mismatch"
    PROJECT_SCOPE_DENIED = "project_scope_denied"
    ROLE_NOT_PERMITTED = "role_not_permitted"
    MEDICAL_DIRECTOR_ROLE_REQUIRED = "medical_director_role_required"
    REAUTHENTICATION_REQUIRED = "reauthentication_required"
    ELECTRONIC_SIGNATURE_REQUIRED = "electronic_signature_required"


READ_ACTIONS = frozenset(
    {
        MonitoringAction.READ_MONITORING,
        MonitoringAction.READ_DASHBOARD,
        MonitoringAction.READ_WORKBENCH_INBOX,
        MonitoringAction.READ_AI_RUN,
        MonitoringAction.READ_AI_ARTIFACT,
        MonitoringAction.READ_SOURCE_EVIDENCE,
        MonitoringAction.READ_RISK_AUDIT,
        MonitoringAction.READ_RUNTIME_AUDIT,
        MonitoringAction.EXPORT_RISK_EVIDENCE,
    }
)

WRITE_ACTIONS = frozenset(
    {
        MonitoringAction.INTAKE_BATCH,
        MonitoringAction.RUN_DETERMINISTIC_RULES,
        MonitoringAction.REVIEW_AI_CANDIDATE,
        MonitoringAction.CHANGE_RISK_DISPOSITION,
        MonitoringAction.DRAFT_QUERY,
        MonitoringAction.CREATE_ASSURANCE_TASK,
        MonitoringAction.RECORD_ASSURANCE_EVIDENCE,
        MonitoringAction.REVIEW_ASSURANCE,
        MonitoringAction.COMPLETE_ASSURANCE,
        MonitoringAction.CONFIRM_HIGH_RISK_CLOSE,
        MonitoringAction.APPROVE_RULE_CHANGE,
        MonitoringAction.PROVIDE_CENTER_CONTEXT,
        MonitoringAction.VALIDATE_SOURCE_REVISION,
        MonitoringAction.MARK_SAFETY_PV_REVIEW,
        MonitoringAction.CONFIRM_DERIVED_DATA,
        MonitoringAction.ADMINISTER_RUNTIME,
    }
)

# These actions are deliberately explicit rather than inferred from a generic
# "write" flag.  A future deployment may bind them to its e-signature system.
E_SIGNATURE_ACTIONS = frozenset(
    {
        MonitoringAction.COMPLETE_ASSURANCE,
        MonitoringAction.CONFIRM_HIGH_RISK_CLOSE,
        MonitoringAction.APPROVE_RULE_CHANGE,
    }
)
HIGH_RISK_CONTEXT_ACTIONS = frozenset(
    {
        MonitoringAction.CHANGE_RISK_DISPOSITION,
        MonitoringAction.COMPLETE_ASSURANCE,
    }
)
DIRECTOR_ONLY_ACTIONS = frozenset(
    {
        MonitoringAction.CONFIRM_HIGH_RISK_CLOSE,
        MonitoringAction.APPROVE_RULE_CHANGE,
    }
)


_ROLE_ACTIONS: dict[MonitoringRole, frozenset[MonitoringAction]] = {
    MonitoringRole.MEDICAL_MONITOR: frozenset(
        {
            MonitoringAction.READ_MONITORING,
            MonitoringAction.READ_DASHBOARD,
            MonitoringAction.READ_WORKBENCH_INBOX,
            MonitoringAction.READ_AI_RUN,
            MonitoringAction.READ_AI_ARTIFACT,
            MonitoringAction.READ_SOURCE_EVIDENCE,
            MonitoringAction.READ_RISK_AUDIT,
            MonitoringAction.REVIEW_AI_CANDIDATE,
            MonitoringAction.CHANGE_RISK_DISPOSITION,
            MonitoringAction.DRAFT_QUERY,
            MonitoringAction.REVIEW_ASSURANCE,
            MonitoringAction.EXPORT_RISK_EVIDENCE,
        }
    ),
    MonitoringRole.MEDICAL_MANAGER: frozenset(
        {
            *READ_ACTIONS - {MonitoringAction.READ_RUNTIME_AUDIT},
            MonitoringAction.INTAKE_BATCH,
            MonitoringAction.RUN_DETERMINISTIC_RULES,
            MonitoringAction.REVIEW_AI_CANDIDATE,
            MonitoringAction.CHANGE_RISK_DISPOSITION,
            MonitoringAction.DRAFT_QUERY,
            MonitoringAction.CREATE_ASSURANCE_TASK,
            MonitoringAction.RECORD_ASSURANCE_EVIDENCE,
            MonitoringAction.REVIEW_ASSURANCE,
            MonitoringAction.COMPLETE_ASSURANCE,
        }
    ),
    MonitoringRole.MEDICAL_DIRECTOR: frozenset(
        {
            *READ_ACTIONS - {MonitoringAction.READ_RUNTIME_AUDIT},
            MonitoringAction.REVIEW_AI_CANDIDATE,
            MonitoringAction.CHANGE_RISK_DISPOSITION,
            MonitoringAction.CREATE_ASSURANCE_TASK,
            MonitoringAction.RECORD_ASSURANCE_EVIDENCE,
            MonitoringAction.REVIEW_ASSURANCE,
            MonitoringAction.COMPLETE_ASSURANCE,
            MonitoringAction.CONFIRM_HIGH_RISK_CLOSE,
            MonitoringAction.APPROVE_RULE_CHANGE,
        }
    ),
    MonitoringRole.MEDICAL_WRITER: frozenset(
        {
            MonitoringAction.READ_MONITORING,
            MonitoringAction.READ_SOURCE_EVIDENCE,
            MonitoringAction.EXPORT_RISK_EVIDENCE,
        }
    ),
    MonitoringRole.CLINICAL_OPERATIONS: frozenset(
        {
            MonitoringAction.READ_MONITORING,
            MonitoringAction.READ_SOURCE_EVIDENCE,
            MonitoringAction.PROVIDE_CENTER_CONTEXT,
        }
    ),
    MonitoringRole.DATA_MANAGEMENT: frozenset(
        {
            MonitoringAction.READ_MONITORING,
            MonitoringAction.READ_SOURCE_EVIDENCE,
            MonitoringAction.VALIDATE_SOURCE_REVISION,
        }
    ),
    MonitoringRole.PV: frozenset(
        {
            MonitoringAction.READ_MONITORING,
            MonitoringAction.READ_SOURCE_EVIDENCE,
            MonitoringAction.MARK_SAFETY_PV_REVIEW,
        }
    ),
    MonitoringRole.STATISTICS_PROGRAMMING: frozenset(
        {
            MonitoringAction.READ_MONITORING,
            MonitoringAction.READ_SOURCE_EVIDENCE,
            MonitoringAction.CONFIRM_DERIVED_DATA,
        }
    ),
    MonitoringRole.SYSTEM_ADMIN: frozenset(
        {
            MonitoringAction.READ_RUNTIME_AUDIT,
            MonitoringAction.ADMINISTER_RUNTIME,
        }
    ),
    MonitoringRole.PRODUCT_ENGINEERING: frozenset(),
}


def _required(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _enum_tuple(
    values: Iterable[Any], enum_type: type[Enum], field_name: str
) -> tuple[Any, ...]:
    if isinstance(values, str):
        values = (values,)
    converted = []
    for value in values or ():
        try:
            item = (
                value if isinstance(value, enum_type) else enum_type(str(value).strip())
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{field_name} contains an unsupported value: {value}"
            ) from exc
        converted.append(item)
    if not converted:
        raise ValueError(f"{field_name} cannot be empty")
    if len(set(converted)) != len(converted):
        raise ValueError(f"{field_name} must be unique")
    return tuple(sorted(converted, key=lambda item: item.value))


def _project_scope(values: Iterable[Any]) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    cleaned = tuple(_required(value, "project_scope item") for value in values or ())
    if not cleaned:
        raise ValueError("project_scope cannot be empty")
    if "*" in cleaned:
        raise ValueError("project_scope cannot contain a wildcard")
    if len(set(cleaned)) != len(cleaned):
        raise ValueError("project_scope must be unique")
    return tuple(sorted(cleaned))


def _sha256_evidence(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


@dataclass(frozen=True)
class MonitoringPrincipal:
    """An explicitly identified principal; no anonymous or wildcard fallback."""

    principal_id: str
    roles: tuple[MonitoringRole, ...]
    project_scope: tuple[str, ...]
    authenticated: bool = False
    authn_method: str = ""
    session_id: str = ""
    directory_revision: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "principal_id", _required(self.principal_id, "principal_id")
        )
        object.__setattr__(
            self,
            "roles",
            _enum_tuple(self.roles, MonitoringRole, "roles"),
        )
        object.__setattr__(self, "project_scope", _project_scope(self.project_scope))
        if not isinstance(self.authenticated, bool):
            raise ValueError("authenticated must be a boolean")
        authn_method = str(self.authn_method or "").strip()
        session_id = str(self.session_id or "").strip()
        directory_revision = str(self.directory_revision or "").strip()
        if self.authenticated and (not authn_method or not session_id):
            raise ValueError(
                "authenticated principals require authn_method and session_id"
            )
        object.__setattr__(self, "authn_method", authn_method)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "directory_revision", directory_revision)

    def public_dict(self) -> dict[str, Any]:
        return {
            "principal_id": self.principal_id,
            "roles": [role.value for role in self.roles],
            "project_scope": list(self.project_scope),
            "authenticated": self.authenticated,
            "authn_method": self.authn_method,
            "session_id_sha256": _digest(self.session_id) if self.session_id else "",
            "directory_revision": self.directory_revision,
        }

    @property
    def principal_sha256(self) -> str:
        return _digest(self.public_dict())


def build_first_release_medical_manager_principal(
    *,
    principal_id: str,
    project_ids: Iterable[str],
    authn_method: str,
    session_id: str,
    directory_revision: str = "first-release-unified-medical-manager-v1",
) -> MonitoringPrincipal:
    """Build the explicit local first-release identity.

    This helper requires the caller to supply a real principal and session.  It
    does not reproduce the router's historical ``actor=medical_manager``
    default and does not imply that production authentication is complete.
    """

    return MonitoringPrincipal(
        principal_id=principal_id,
        roles=(MonitoringRole.MEDICAL_MANAGER,),
        project_scope=tuple(project_ids),
        authenticated=True,
        authn_method=authn_method,
        session_id=session_id,
        directory_revision=directory_revision,
    )


@dataclass(frozen=True)
class MonitoringAuthorizationRequest:
    request_id: str
    principal_id: str
    project_id: str
    action: MonitoringAction
    target_scope: MonitoringScopeType
    high_risk: bool = False
    reauthenticated: bool = False
    signature_evidence_sha256: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _required(self.request_id, "request_id"))
        object.__setattr__(
            self, "principal_id", _required(self.principal_id, "principal_id")
        )
        object.__setattr__(self, "project_id", _required(self.project_id, "project_id"))
        if not isinstance(self.action, MonitoringAction):
            object.__setattr__(self, "action", MonitoringAction(self.action))
        if self.target_scope not in {"trial", "site", "subject"}:
            raise ValueError(f"unsupported target_scope: {self.target_scope}")
        if not isinstance(self.high_risk, bool) or not isinstance(
            self.reauthenticated, bool
        ):
            raise ValueError("high_risk and reauthenticated must be booleans")
        signature = self.signature_evidence_sha256
        if signature:
            signature = _sha256_evidence(signature, "signature_evidence_sha256")
        object.__setattr__(self, "signature_evidence_sha256", signature)

    def public_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "principal_id": self.principal_id,
            "project_id": self.project_id,
            "action": self.action.value,
            "target_scope": self.target_scope,
            "high_risk": self.high_risk,
            "reauthenticated": self.reauthenticated,
            "signature_evidence_sha256": self.signature_evidence_sha256,
        }


@dataclass(frozen=True)
class MonitoringAuthorizationDecision:
    request_id: str
    principal_id: str
    principal_sha256: str
    project_id: str
    action: MonitoringAction
    target_scope: MonitoringScopeType
    allowed: bool
    reason: MonitoringAuthorizationReason
    matched_roles: tuple[MonitoringRole, ...]
    requires_reauthentication: bool
    requires_e_signature: bool
    write_permitted: bool
    decision_sha256: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "matched_roles", tuple(self.matched_roles))
        payload = self.public_dict()
        decision_sha256 = _digest(payload)
        if self.decision_sha256 and self.decision_sha256 != decision_sha256:
            raise ValueError(
                "decision_sha256 does not match immutable authorization decision"
            )
        object.__setattr__(self, "decision_sha256", decision_sha256)

    def public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MONITORING_AUTHORIZATION_SCHEMA_VERSION,
            "request_id": self.request_id,
            "principal_id": self.principal_id,
            "principal_sha256": self.principal_sha256,
            "project_id": self.project_id,
            "action": self.action.value,
            "target_scope": self.target_scope,
            "allowed": self.allowed,
            "reason": self.reason.value,
            "matched_roles": [role.value for role in self.matched_roles],
            "requires_reauthentication": self.requires_reauthentication,
            "requires_e_signature": self.requires_e_signature,
            "write_permitted": self.write_permitted,
        }


def _decision(
    principal: MonitoringPrincipal,
    request: MonitoringAuthorizationRequest,
    *,
    allowed: bool,
    reason: MonitoringAuthorizationReason,
    matched_roles: tuple[MonitoringRole, ...],
    requires_reauthentication: bool,
    requires_e_signature: bool,
) -> MonitoringAuthorizationDecision:
    return MonitoringAuthorizationDecision(
        request_id=request.request_id,
        principal_id=principal.principal_id,
        principal_sha256=principal.principal_sha256,
        project_id=request.project_id,
        action=request.action,
        target_scope=request.target_scope,
        allowed=allowed,
        reason=reason,
        matched_roles=matched_roles,
        requires_reauthentication=requires_reauthentication,
        requires_e_signature=requires_e_signature,
        write_permitted=allowed and request.action in WRITE_ACTIONS,
    )


def authorize_monitoring_action(
    principal: MonitoringPrincipal,
    request: MonitoringAuthorizationRequest,
) -> MonitoringAuthorizationDecision:
    """Evaluate one fail-closed, project-scoped monitoring action.

    The returned ``write_permitted`` flag is an authorization result only.  A
    caller still needs the runtime repository, audit append and source-revision
    checks before making a controlled write.
    """

    matched_roles = tuple(
        role
        for role in principal.roles
        if request.action in _ROLE_ACTIONS.get(role, frozenset())
    )
    common = {
        "matched_roles": matched_roles,
        "requires_reauthentication": request.action in E_SIGNATURE_ACTIONS
        or (request.high_risk and request.action in HIGH_RISK_CONTEXT_ACTIONS),
        "requires_e_signature": request.action in E_SIGNATURE_ACTIONS
        or (request.high_risk and request.action in HIGH_RISK_CONTEXT_ACTIONS),
    }
    if request.principal_id != principal.principal_id:
        return _decision(
            principal,
            request,
            allowed=False,
            reason=MonitoringAuthorizationReason.PRINCIPAL_MISMATCH,
            **common,
        )
    if not principal.authenticated:
        return _decision(
            principal,
            request,
            allowed=False,
            reason=MonitoringAuthorizationReason.AUTHENTICATION_REQUIRED,
            **common,
        )
    if request.project_id not in principal.project_scope:
        return _decision(
            principal,
            request,
            allowed=False,
            reason=MonitoringAuthorizationReason.PROJECT_SCOPE_DENIED,
            **common,
        )
    if (
        request.action in DIRECTOR_ONLY_ACTIONS
        and MonitoringRole.MEDICAL_DIRECTOR not in matched_roles
    ):
        return _decision(
            principal,
            request,
            allowed=False,
            reason=MonitoringAuthorizationReason.MEDICAL_DIRECTOR_ROLE_REQUIRED,
            **common,
        )
    if not matched_roles:
        return _decision(
            principal,
            request,
            allowed=False,
            reason=MonitoringAuthorizationReason.ROLE_NOT_PERMITTED,
            **common,
        )
    if common["requires_reauthentication"] and not request.reauthenticated:
        return _decision(
            principal,
            request,
            allowed=False,
            reason=MonitoringAuthorizationReason.REAUTHENTICATION_REQUIRED,
            **common,
        )
    if common["requires_e_signature"] and not request.signature_evidence_sha256:
        return _decision(
            principal,
            request,
            allowed=False,
            reason=MonitoringAuthorizationReason.ELECTRONIC_SIGNATURE_REQUIRED,
            **common,
        )
    return _decision(
        principal,
        request,
        allowed=True,
        reason=MonitoringAuthorizationReason.AUTHORIZED,
        **common,
    )


def authorization_decision_payload(
    decision: MonitoringAuthorizationDecision,
) -> dict[str, Any]:
    """Return a JSON-safe payload suitable for a later append-only audit event."""

    payload = decision.public_dict()
    payload["decision_sha256"] = decision.decision_sha256
    return payload
