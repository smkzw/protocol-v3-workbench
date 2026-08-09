from __future__ import annotations

from enum import Enum
import re
from typing import Any, Mapping


class MonitoringFieldKind(str, Enum):
    SOURCE_COLLECTED = "source_collected"
    SOURCE_METADATA = "source_metadata"
    STANDARDIZED_CODED = "standardized_coded"
    DETERMINISTIC_DERIVED = "deterministic_derived"
    UNMAPPED = "unmapped"


_IP_ROLE_MARKERS = (
    "investigational",
    "试验药物",
    "研究药物",
    "剂量调整",
    "停药",
    "重启",
)
_ROLE_TOKEN_RE = re.compile(r"[._/\s:-]+")
_NON_SPECIFIC_CODING_SYSTEM_RE = re.compile(
    r"(?:unspecified|unknown|待确认|未指定|不明确|不详)",
    re.IGNORECASE,
)
_DICTIONARY_VERSION_FIELD_RE = re.compile(
    r"(?:^|[_-])(?:M?DRAVER|DRUGVER|WHODDVER|DICT(?:IONARY)?VER"
    r"|CODELISTVER|CODINGVER|VERSION|VER)(?:$|[_-])",
    re.IGNORECASE,
)
_UNCERTAIN_FORMULA_RE = re.compile(
    r"(?:待确认|可能|推测|假设|未知|未提供|不明确|不详|"
    r"to\s+be\s+confirmed|unknown|unspecified|may\s+be)",
    re.IGNORECASE,
)


def validate_monitoring_mapping_semantics(
    *,
    domain: str,
    source_field: str = "",
    recommended_role: str,
    field_kind: MonitoringFieldKind,
    standards_reference: Mapping[str, Any] | None,
    derivation_lineage: Mapping[str, Any] | None,
) -> None:
    role = recommended_role.strip().casefold()
    if "sdtm" in role:
        raise ValueError("SDTM concepts may appear only in standards_reference")
    if domain.strip().upper() == "CM" and _contains_ip_role_marker(role):
        raise ValueError(
            "CM is non-investigational medication only; IP roles are separate"
        )
    if standards_reference is not None and (
        standards_reference.get("reference_only") is not True
    ):
        raise ValueError("standards reference must remain reference-only")

    if field_kind == MonitoringFieldKind.STANDARDIZED_CODED:
        source_fields = _require_lineage_text_list(
            derivation_lineage,
            "source_fields",
        )
        _require_lineage_text(derivation_lineage, "coding_system")
        coding_system = str(
            (derivation_lineage or {}).get("coding_system", "")
        ).strip()
        if _NON_SPECIFIC_CODING_SYSTEM_RE.search(coding_system):
            raise ValueError(
                "standardized coded mapping requires an explicit coding system"
            )
        if source_field.strip() and source_field.strip() in source_fields:
            raise ValueError(
                "standardized coded mapping cannot use the target field as "
                "its own lineage source"
            )
        if not any(
            str((derivation_lineage or {}).get(key, "")).strip()
            for key in ("dictionary_version", "dictionary_version_field")
        ):
            raise ValueError(
                "standardized coded mapping requires dictionary version "
                "or dictionary_version_field"
            )
        version_field = str(
            (derivation_lineage or {}).get("dictionary_version_field", "")
        ).strip()
        if version_field and (
            version_field == source_field.strip()
            or not _DICTIONARY_VERSION_FIELD_RE.search(version_field)
        ):
            raise ValueError(
                "dictionary_version_field must be an independent version field"
            )
    elif field_kind == MonitoringFieldKind.DETERMINISTIC_DERIVED:
        source_fields = _require_lineage_text_list(
            derivation_lineage,
            "source_fields",
        )
        _require_lineage_text(derivation_lineage, "formula")
        if source_field.strip() and source_field.strip() in source_fields:
            raise ValueError(
                "deterministic derived mapping cannot use the target field as "
                "its own source"
            )
        formula = str((derivation_lineage or {}).get("formula", "")).strip()
        if _UNCERTAIN_FORMULA_RE.search(formula):
            raise ValueError(
                "deterministic derived mapping requires an explicit formula"
            )
        if (derivation_lineage or {}).get("user_confirmed") is not True:
            raise ValueError(
                "deterministic derived mapping requires explicit user confirmation"
            )
    elif derivation_lineage:
        raise ValueError(
            "only coded or deterministic derived mappings may define lineage"
        )


def _require_lineage_text(
    lineage: Mapping[str, Any] | None,
    key: str,
) -> None:
    if not isinstance(lineage, Mapping) or not str(lineage.get(key, "")).strip():
        raise ValueError(f"mapping lineage requires {key}")


def _require_lineage_text_list(
    lineage: Mapping[str, Any] | None,
    key: str,
) -> tuple[str, ...]:
    value = lineage.get(key) if isinstance(lineage, Mapping) else None
    if (
        not isinstance(value, (list, tuple))
        or not value
        or any(not str(item).strip() for item in value)
    ):
        raise ValueError(f"mapping lineage requires non-empty {key}")
    return tuple(str(item).strip() for item in value)


def _contains_ip_role_marker(role: str) -> bool:
    """Detect IP roles without misclassifying the canonical ``cm.non_ip_*`` role."""
    tokens = [token for token in _ROLE_TOKEN_RE.split(role) if token]
    for index, token in enumerate(tokens):
        if token == "ip":
            if index and tokens[index - 1] == "non":
                continue
            return True
    return any(marker.casefold() in role for marker in _IP_ROLE_MARKERS)
