"""Legacy v2→v3 migration inventory and quarantine typed primitives (Task 1.10).

This package is the read-only front door of the v2→v3 strangler migration.  It
contains only pure, immutable, JSON-canonical primitives:

* :class:`LegacySourceRecord` / :class:`ImmutableLocator` /
  :class:`SourceRevisionToken` — frozen identity + original payload with a
  computed payload/locator hash;
* :class:`InventorySnapshot` — deterministic, permutation-stable inventory
  with the accounting invariant
  ``source_count == record_count + quarantined_count + deduplicated_count``;
* :class:`QuarantineReason` / :class:`QuarantineRecord` — closed reason
  vocabulary with stable Chinese-safe metadata and original source
  hash/locator binding.

Guarantees relevant to later tasks: no database access, no runtime singleton
import, no semantic-node inference, no source mutation (payloads are
deep-frozen copies), and duplicate identity with divergent payload fails
closed into explicit quarantine.  The mapping/cutover layers live in sibling
modules owned by later workers; this package never performs a write.
"""

from __future__ import annotations

from .quarantine import (
    FAMILY_PUBLIC_LABEL_ZH,
    QUARANTINE_REASON_CATALOG,
    QuarantineReason,
    QuarantineReasonKind,
    QuarantineRecord,
    quarantine_reason,
)
from .migration_inventory import (
    INVENTORY_SCHEMA_VERSION,
    LEGACY_SOURCE_FAMILIES,
    ImmutableLocator,
    InventorySnapshot,
    LegacySourceFamily,
    LegacySourceRecord,
    SourceRevisionToken,
    build_inventory,
)

__all__ = [
    "FAMILY_PUBLIC_LABEL_ZH",
    "INVENTORY_SCHEMA_VERSION",
    "ImmutableLocator",
    "InventorySnapshot",
    "LEGACY_SOURCE_FAMILIES",
    "LegacySourceFamily",
    "LegacySourceRecord",
    "QUARANTINE_REASON_CATALOG",
    "QuarantineReason",
    "QuarantineReasonKind",
    "QuarantineRecord",
    "SourceRevisionToken",
    "build_inventory",
    "quarantine_reason",
]
