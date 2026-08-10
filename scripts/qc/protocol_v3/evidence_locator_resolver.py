"""Protocol v3 Phase 0 Task 0.5 evidence locator resolver.

This module resolves and plans recovery for quarantine moves.  It is the
read-only, idempotent core of the recoverable-hygiene toolchain: given a
PATH_MAP it can answer "where did this live object come from?" (new -> old)
and "where did this live path go to?" (old -> new), verify content hashes,
and emit a pure restore plan.

Hard contract (fail closed on everything):

- The resolver NEVER copies, moves, links, or deletes anything.  It performs
  no filesystem mutation whatsoever.  Restore planning is pure: it returns a
  plan describing the operations an external actor would perform; it does not
  execute them.
- Every PATH_MAP is validated on load: schema version, required top-level
  keys, entry shape, absolute non-traversal old locators, quarantine-relative
  content-addressed new locators, SHA-256 hashes, byte sizes, path types,
  owner, reason, operation and recovery metadata.
- Duplicate old locators, duplicate or conflicting ids / content addresses,
  destination collisions with different hashes, missing objects, wrong
  hashes/sizes/types, traversal attempts, symlink old locators, and ambiguous
  reverse lookups are all rejected.
- The module is independent of any current live candidate state: it defines
  and validates the versioned PATH_MAP schema and operates on explicit inputs
  only.  It does not import application code and does not touch the real
  quarantine root.

Tests in test_repository_hygiene_mutator.py prove the round-trip plus every
failure class using only task-owned temporary fixtures.
"""

from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Iterable, Iterator, Mapping, Sequence


PATH_MAP_SCHEMA_VERSION = 1
POLICY_ID = "mw-protocol-v3-evidence-locator-resolver-v1"

# Operations admitted by the recoverable-hygiene toolchain.
OPERATION_QUARANTINE_MOVE = "quarantine_move"
OPERATION_DIRECT_DELETE = "direct_delete"
VALID_OPERATIONS = (OPERATION_QUARANTINE_MOVE, OPERATION_DIRECT_DELETE)

# Lifecycle status values a PATH_MAP entry may carry.  The resolver accepts
# any of these on load (the mutator owns transitions); the resolver itself
# never sets a status.
VALID_STATUSES = (
    "planned",
    "copied",
    "committed",
    "restored",
    "skipped",
    "failed",
)

# Path types consistent with the Task 0.2 inventory metadata.  Symlinks are
# deliberately rejected as old locators: a quarantine move must target a real
# regular file so that a restore is byte-for-byte reproducible.
VALID_PATH_TYPES = ("file",)

REQUIRED_TOP_LEVEL_KEYS = (
    "schema_version",
    "task_id",
    "quarantine_root",
    "expected_inventory_sha256",
    "expected_protected_sha256",
    "entries",
)

REQUIRED_ENTRY_KEYS = (
    "id",
    "operation",
    "owner",
    "reason",
    "old_locator",
    "path_type",
    "size",
    "source_sha256",
    "content_address",
    "recovery_command",
    "status",
)

# All top-level keys are required, so the allowed set equals the required set.
ALLOWED_TOP_LEVEL_KEYS = frozenset(REQUIRED_TOP_LEVEL_KEYS)

# Entry keys allowed in schema v1: the required keys plus the two optional
# locator/hash fields.  Any other key is rejected so a PATH_MAP cannot carry
# undocumented fields that bypass validation.
OPTIONAL_ENTRY_KEYS = ("new_locator", "destination_sha256")
ALLOWED_ENTRY_KEYS = frozenset(REQUIRED_ENTRY_KEYS + OPTIONAL_ENTRY_KEYS)

_HEX = set("0123456789abcdef")


class ResolverError(RuntimeError):
    """Raised when a PATH_MAP cannot be resolved without guessing.

    Every recovery-relevant ambiguity, drift, or integrity failure raises this
    so the caller fails closed rather than silently inventing a mapping.
    """


# --------------------------------------------------------------------------- #
# Internal path helpers (lexically absolute, symlink-safe, traversal-safe).
# --------------------------------------------------------------------------- #


def _lexical_absolute(value: str | os.PathLike[str]) -> Path:
    """Return a lexically normalized absolute path without resolving symlinks.

    Mirrors the convention in build_frozen_authority_manifest.py so that the
    resolver and the protection manifest agree on path identity.
    """

    path = Path(os.path.abspath(os.fspath(value)))
    if path.is_symlink():
        raise ResolverError(
            "locator must not be a symlink: %s" % path
        )
    return path


def _sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        raise ResolverError("sha256 must be a string, got %s" % type(value).__name__)
    if len(value) != 64 or any(ch not in _HEX for ch in value):
        raise ResolverError("invalid sha256 hex: %r" % value)
    return value


def _is_hex_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(ch in _HEX for ch in value)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    """Stream-hash a regular file.  Public so the mutator and tests share it."""

    path = _lexical_absolute(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _within_lexical(child: Path, root: Path) -> bool:
    """True when ``child`` is lexically inside ``root`` (no symlink resolution)."""

    try:
        Path(os.path.relpath(child, root))
    except ValueError:
        return False
    rel = os.path.relpath(str(child), str(root))
    if rel == ".":
        return True
    return not rel.startswith(".." + os.sep) and rel != ".."


def _require_raw_absolute(value: str, field: str) -> None:
    """Reject a path string that is not already absolute.

    ``_lexical_absolute`` calls ``os.path.abspath``, which silently promotes a
    relative path to absolute by prepending the current working directory.  For
    a recoverable-hygiene PATH_MAP that is dangerous: a relative old_locator or
    quarantine_root would mean different physical files depending on CWD.  We
    therefore require the raw input to be absolute and fail closed otherwise.
    """

    if not os.path.isabs(value):
        raise ResolverError("%s must be an absolute path, got %r" % (field, value))


def _validate_quarantine_root(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ResolverError("quarantine_root must be a non-empty string")
    if _has_traversal(value):
        raise ResolverError("quarantine_root must not contain traversal: %s" % value)
    _require_raw_absolute(value, "quarantine_root")
    root = _lexical_absolute(value)
    # The resolver never creates or requires the quarantine root to exist; it
    # only validates its lexical shape.
    return root


def _has_traversal(value: str) -> bool:
    """True when a raw path string contains a ``..`` path component.

    Detected on the raw string BEFORE normalization so that an attempt to
    escape via ``..`` is rejected even when ``os.path.abspath`` would later
    collapse it.  Both POSIX and OS-native separators are checked.
    """

    for part in value.replace("\\", "/").split("/"):
        if part == "..":
            return True
    return False


def _validate_old_locator(value: Any, quarantine_root: Path) -> Path:
    """Validate an old (live-side) locator.

    It must be absolute (checked on the RAW string, before normalization, so a
    relative path is rejected rather than silently CWD-promoted), non-traversal,
    non-symlink, and outside the quarantine root.  Symlink old locators are
    rejected because a restore must be byte-for-byte reproducible against a
    real file.
    """

    if not isinstance(value, str) or not value.strip():
        raise ResolverError("old_locator must be a non-empty string")
    if _has_traversal(value):
        raise ResolverError(
            "old_locator must not contain traversal segments: %s" % value
        )
    _require_raw_absolute(value, "old_locator")
    locator = _lexical_absolute(value)
    if _within_lexical(locator, quarantine_root):
        raise ResolverError(
            "old_locator must live outside the quarantine root: %s" % locator
        )
    return locator


def _validate_new_locator(
    value: Any,
    quarantine_root: Path,
    content_address: str,
) -> str | None:
    """Validate a new (quarantine-side) content-addressed locator.

    For ``quarantine_move`` the new locator must be a POSIX-relative path under
    ``objects/<content_address[:2]>/<content_address>`` inside the quarantine
    root and must contain no traversal.  For ``direct_delete`` it must be null
    (there is no quarantine object).
    """

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ResolverError("new_locator must be null or a non-empty string")
    rel = PurePosixPath(value)
    if rel.is_absolute() or ".." in rel.parts:
        raise ResolverError(
            "new_locator must be a relative, traversal-free path: %s" % value
        )
    expected = PurePosixPath("objects") / content_address[:2] / content_address
    # PurePosixPath equality normalizes harmless ``.`` segments, so
    # ``objects/aa/./<hash>`` would compare equal to the canonical form.
    # Reject any spelling that is not already canonical so the stored key,
    # reverse index and fingerprint all share one identity.
    canonical = expected.as_posix()
    if value != canonical:
        raise ResolverError(
            "new_locator %r must equal the canonical content-address path %s"
            % (value, canonical)
        )
    full = quarantine_root / expected
    if not _within_lexical(full, quarantine_root):
        raise ResolverError(
            "new_locator must stay inside the quarantine root: %s" % value
        )
    return canonical


# --------------------------------------------------------------------------- #
# PATH_MAP validation and load.
# --------------------------------------------------------------------------- #


def validate_path_map(data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate a PATH_MAP mapping in depth and return a normalized copy.

    The returned mapping is a freshly built, deterministic structure: locators
    are lexically normalized (so ``/a/./b`` and ``/a/b`` share one identity),
    every entry carries exactly the schema-v1 fields in a stable order, and the
    caller's input object is never mutated.  Raises ``ResolverError`` on any
    structural or semantic problem so that callers fail closed.
    """

    if not isinstance(data, Mapping):
        raise ResolverError("PATH_MAP must be a JSON object")

    missing = [key for key in REQUIRED_TOP_LEVEL_KEYS if key not in data]
    if missing:
        raise ResolverError("PATH_MAP missing required keys: %s" % ", ".join(missing))

    unknown_top = [key for key in data if key not in ALLOWED_TOP_LEVEL_KEYS]
    if unknown_top:
        raise ResolverError(
            "PATH_MAP unknown top-level keys: %s" % ", ".join(sorted(unknown_top))
        )

    schema_version = data["schema_version"]
    if schema_version != PATH_MAP_SCHEMA_VERSION:
        raise ResolverError(
            "unsupported PATH_MAP schema_version: %r (expected %d)"
            % (schema_version, PATH_MAP_SCHEMA_VERSION)
        )

    task_id = data["task_id"]
    if not isinstance(task_id, str) or not task_id.strip():
        raise ResolverError("task_id must be a non-empty string")

    quarantine_root = _validate_quarantine_root(data["quarantine_root"])

    expected_inventory_sha256 = _sha256_hex(data["expected_inventory_sha256"])
    expected_protected_sha256 = _sha256_hex(data["expected_protected_sha256"])

    entries = data["entries"]
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise ResolverError("PATH_MAP entries must be a list")
    if len(entries) == 0:
        raise ResolverError("PATH_MAP must contain at least one entry")

    # First pass: validate each entry in isolation.
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(entries):
        if not isinstance(raw, Mapping):
            raise ResolverError("PATH_MAP entry %d must be a JSON object" % index)
        missing_entry = [key for key in REQUIRED_ENTRY_KEYS if key not in raw]
        if missing_entry:
            raise ResolverError(
                "PATH_MAP entry %d missing keys: %s" % (index, ", ".join(missing_entry))
            )
        unknown_entry = [key for key in raw if key not in ALLOWED_ENTRY_KEYS]
        if unknown_entry:
            raise ResolverError(
                "PATH_MAP entry %d unknown keys: %s"
                % (index, ", ".join(sorted(unknown_entry)))
            )
        normalized.append(
            _validate_entry(raw, index, quarantine_root)
        )

    # Second pass: cross-entry integrity (uniqueness and collisions).
    _validate_entry_uniqueness(normalized)

    # Build a fresh, deterministic mapping.  The caller's input is untouched.
    return {
        "schema_version": PATH_MAP_SCHEMA_VERSION,
        "task_id": task_id,
        "quarantine_root": str(quarantine_root),
        "expected_inventory_sha256": expected_inventory_sha256,
        "expected_protected_sha256": expected_protected_sha256,
        "entries": normalized,
    }
def _validate_entry(
    raw: Mapping[str, Any],
    index: int,
    quarantine_root: Path,
) -> dict[str, Any]:
    entry_id = raw["id"]
    if not isinstance(entry_id, str) or not entry_id.strip():
        raise ResolverError("entry %d id must be a non-empty string" % index)

    operation = raw["operation"]
    if operation not in VALID_OPERATIONS:
        raise ResolverError(
            "entry %d operation %r not in %s" % (index, operation, VALID_OPERATIONS)
        )

    owner = raw["owner"]
    if not isinstance(owner, str) or not owner.strip():
        raise ResolverError("entry %d owner must be a non-empty string" % index)

    reason = raw["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise ResolverError("entry %d reason must be a non-empty string" % index)

    old_locator = _validate_old_locator(raw["old_locator"], quarantine_root)

    path_type = raw["path_type"]
    if path_type not in VALID_PATH_TYPES:
        raise ResolverError(
            "entry %d path_type %r not in %s (symlinks are not movable)"
            % (index, path_type, VALID_PATH_TYPES)
        )

    size = raw["size"]
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ResolverError("entry %d size must be a non-negative integer" % index)

    source_sha256 = _sha256_hex(raw["source_sha256"])
    content_address = _sha256_hex(raw["content_address"])

    recovery_command = raw["recovery_command"]
    if not isinstance(recovery_command, str) or not recovery_command.strip():
        raise ResolverError(
            "entry %d recovery_command must be a non-empty string" % index
        )

    status = raw["status"]
    if status not in VALID_STATUSES:
        raise ResolverError(
            "entry %d status %r not in %s" % (index, status, VALID_STATUSES)
        )

    destination_sha256 = raw.get("destination_sha256")
    new_locator = raw.get("new_locator")

    if operation == OPERATION_QUARANTINE_MOVE:
        new_locator_validated = _validate_new_locator(
            new_locator, quarantine_root, content_address
        )
        if new_locator_validated is None:
            raise ResolverError(
                "entry %d quarantine_move requires a non-null new_locator" % index
            )
        if destination_sha256 is None:
            raise ResolverError(
                "entry %d quarantine_move requires destination_sha256" % index
            )
        destination_sha256 = _sha256_hex(destination_sha256)
        if destination_sha256 != source_sha256:
            raise ResolverError(
                "entry %d destination_sha256 differs from source_sha256"
                " (copy must be byte-identical)" % index
            )
        # The content-address id must equal the source content hash.
        if content_address != source_sha256:
            raise ResolverError(
                "entry %d content_address must equal source_sha256 for a move"
                % index
            )
    else:  # OPERATION_DIRECT_DELETE
        if new_locator is not None:
            raise ResolverError(
                "entry %d direct_delete must have null new_locator" % index
            )
        if destination_sha256 is not None:
            raise ResolverError(
                "entry %d direct_delete must have null destination_sha256" % index
            )
        # content_address for a delete is the source hash (still required so the
        # delete is auditable and reversible into a restore-from-known-content).
        if content_address != source_sha256:
            raise ResolverError(
                "entry %d content_address must equal source_sha256 for a delete"
                % index
            )

    return {
        "id": entry_id,
        "operation": operation,
        "owner": owner,
        "reason": reason,
        "old_locator": str(old_locator),
        "new_locator": new_locator_validated if operation == OPERATION_QUARANTINE_MOVE else None,
        "path_type": path_type,
        "size": size,
        "source_sha256": source_sha256,
        "destination_sha256": destination_sha256,
        "content_address": content_address,
        "recovery_command": recovery_command,
        "status": status,
    }


def _validate_entry_uniqueness(entries: Sequence[Mapping[str, Any]]) -> None:
    seen_ids: dict[str, int] = {}
    seen_old: dict[str, int] = {}
    seen_content: dict[str, int] = {}
    # For quarantine moves the (quarantine_root-relative) new locator must be a
    # unique destination; two entries claiming the same destination object with
    # different source hashes is a collision that must fail closed.
    seen_destination: dict[str, tuple[int, str]] = {}

    for index, entry in enumerate(entries):
        entry_id = entry["id"]
        if entry_id in seen_ids:
            raise ResolverError(
                "duplicate entry id %r at entries %d and %d"
                % (entry_id, seen_ids[entry_id], index)
            )
        seen_ids[entry_id] = index

        old = entry["old_locator"]
        if old in seen_old:
            raise ResolverError(
                "duplicate old_locator %r at entries %d and %d"
                % (old, seen_old[old], index)
            )
        seen_old[old] = index

        content = entry["content_address"]
        # Content address may legitimately repeat across two distinct old
        # locators only when BOTH refer to the same destination object and the
        # hashes agree (deduplicated content).  We still require id uniqueness.
        if content in seen_content:
            prev = seen_content[content]
            if entries[prev]["source_sha256"] != entry["source_sha256"]:
                raise ResolverError(
                    "conflicting content_address %r: entries %d and %d differ in hash"
                    % (content, prev, index)
                )
        else:
            seen_content[content] = index

        if entry["operation"] == OPERATION_QUARANTINE_MOVE:
            dest = entry["new_locator"]
            if dest in seen_destination:
                prev_index, prev_hash = seen_destination[dest]
                if prev_hash != entry["source_sha256"]:
                    raise ResolverError(
                        "destination collision at %r: entries %d and %d differ in hash"
                        % (dest, prev_index, index)
                    )
            else:
                seen_destination[dest] = (index, entry["source_sha256"])


# --------------------------------------------------------------------------- #
# Public resolver.
# --------------------------------------------------------------------------- #


def _deep_freeze(value: Any) -> Any:
    """Recursively freeze JSON-like value into read-only proxy wrappers.

    Dicts become ``MappingProxyType`` (read-only mapping views); lists become
    tuples.  Scalars (str/int/None/bool) are returned unchanged.  This makes
    internal state structurally immutable so accidental ``entry["x"] = ...``
    raises ``TypeError`` rather than silently corrupting indexes or the
    fingerprint.  Only JSON-safe leaf types are expected (the validator has
    already rejected anything else).
    """

    if isinstance(value, Mapping):
        return MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _egress_copy(value: Any) -> Any:
    """Return a deep copy for egress so callers cannot alias internal state."""

    return copy.deepcopy(value)


class EvidenceLocatorResolver:
    """Bidirectional old<->new locator resolver over a validated PATH_MAP.

    Instances are immutable views of a single validated PATH_MAP.  Construction
    validates the map; all lookups are pure and never touch the filesystem or
    the quarantine root.  The resolver is intentionally ignorant of whether the
    quarantine root or any object currently exists: that is the mutator's
    apply-time concern.
    """
    def __init__(self, path_map: Mapping[str, Any]) -> None:
        # validate_path_map returns a fresh normalized dict that is fully
        # independent of the caller's input.  Internal state is kept as plain
        # dicts; every public egress path returns a deep copy so no external
        # alias into internal state can exist.  The caller's original map never
        # retains an alias into internal state.
        normalized = validate_path_map(path_map)
        self._path_map: Mapping[str, Any] = normalized
        self._quarantine_root = _lexical_absolute(str(normalized["quarantine_root"]))
        self._entries: list[Mapping[str, Any]] = list(normalized["entries"])
        self._by_old: dict[str, Mapping[str, Any]] = {
            str(entry["old_locator"]): entry for entry in self._entries
        }
        # new_locator is stored in canonical POSIX form by the validator, so the
        # reverse index key is canonical.  Lookup inputs are normalized to the
        # same identity before probing this index.
        self._by_new: dict[str, Mapping[str, Any]] = {
            str(entry["new_locator"]): entry
            for entry in self._entries
            if entry["operation"] == OPERATION_QUARANTINE_MOVE
        }

    # -- introspection ----------------------------------------------------- #

    @property
    def path_map(self) -> Mapping[str, Any]:
        """Return a deep copy so callers cannot alias internal state."""

        return _egress_copy(self._path_map)

    @property
    def quarantine_root(self) -> Path:
        return self._quarantine_root

    @property
    def task_id(self) -> str:
        return str(self._path_map["task_id"])

    @property
    def expected_inventory_sha256(self) -> str:
        return str(self._path_map["expected_inventory_sha256"])

    @property
    def expected_protected_sha256(self) -> str:
        return str(self._path_map["expected_protected_sha256"])

    def entries(self) -> Iterator[Mapping[str, Any]]:
        """Yield defensive deep copies so callers cannot mutate internals."""

        for entry in self._entries:
            yield _egress_copy(entry)

    # -- forward / reverse lookup ------------------------------------------ #

    def resolve_old_to_new(self, old_locator: str | os.PathLike[str]) -> Mapping[str, Any]:
        """Return a deep copy of the PATH_MAP entry for an old (live-side) locator.

        The raw input must be absolute and traversal-free; harmless ``/./``
        segments are normalized so canonical and dotted spellings share one
        identity.  A relative input is rejected before normalization so it is
        never silently CWD-promoted.  Raises ``ResolverError`` if the locator
        is absent.  The returned mapping is a defensive copy; mutating it
        cannot affect internal state.
        """

        if isinstance(old_locator, os.PathLike) and not isinstance(old_locator, str):
            raw = os.fspath(old_locator)
        else:
            raw = old_locator  # type: ignore[assignment]
        if not isinstance(raw, str) or not raw.strip():
            raise ResolverError("old_locator must be a non-empty path string")
        if _has_traversal(raw):
            raise ResolverError(
                "old_locator must not contain traversal segments: %s" % raw
            )
        if not os.path.isabs(raw):
            raise ResolverError(
                "old_locator must be an absolute path, got %r" % raw
            )
        key = str(_lexical_absolute(raw))
        entry = self._by_old.get(key)
        if entry is None:
            raise ResolverError("no PATH_MAP entry for old_locator: %s" % key)
        return _egress_copy(entry)

    def resolve_new_to_old(self, new_locator: str) -> Mapping[str, Any]:
        """Return a deep copy of the entry for a quarantine-side content locator.

        Accepts either the quarantine-root-relative canonical locator or an
        absolute path inside the quarantine root.  Raw ``..`` traversal is
        rejected on the raw string BEFORE normalization for both absolute and
        relative inputs, so a path like ``<root>/tmp/../objects/...`` cannot
        collapse into the quarantine tree.  Harmless ``/./`` segments are
        normalized.  Absolute inputs must normalize to a path strictly inside
        the quarantine root.  The returned mapping is a defensive copy;
        mutating it cannot affect internal state.
        """

        if not isinstance(new_locator, str) or not new_locator.strip():
            raise ResolverError("new_locator must be a non-empty string")
        # Raw traversal rejection BEFORE any normalization for both branches.
        if _has_traversal(new_locator):
            raise ResolverError(
                "new_locator must not contain traversal: %s" % new_locator
            )
        candidate = PurePosixPath(new_locator)
        if candidate.is_absolute():
            # Normalize the absolute path, then require it inside the
            # (already-normalized) quarantine root.  ``relative_to`` raises
            # ValueError when the path escapes, which we convert to a fail.
            abs_path = _lexical_absolute(new_locator)
            try:
                rel = abs_path.relative_to(self._quarantine_root)
            except ValueError:
                raise ResolverError(
                    "absolute new_locator outside quarantine root: %s" % new_locator
                )
            key = PurePosixPath(rel).as_posix()
        else:
            # Relative input: normalize harmless ``.`` to the canonical POSIX
            # form shared with the reverse index.
            key = PurePosixPath(new_locator).as_posix()

        entry = self._by_new.get(key)
        if entry is None:
            raise ResolverError("no PATH_MAP entry for new_locator: %s" % new_locator)
        return _egress_copy(entry)

    def has_old_locator(self, old_locator: str | os.PathLike[str]) -> bool:
        try:
            self.resolve_old_to_new(old_locator)
        except ResolverError:
            return False
        return True

    def has_new_locator(self, new_locator: str) -> bool:
        try:
            self.resolve_new_to_old(new_locator)
        except ResolverError:
            return False
        return True

    # -- content verification ---------------------------------------------- #

    def verify_object_against_entry(
        self,
        new_locator: str,
        object_path: Path,
    ) -> Mapping[str, Any]:
        """Verify a real quarantine object matches its PATH_MAP entry.

        ``object_path`` must be a regular file whose SHA-256 equals the
        entry's ``destination_sha256``/``source_sha256`` and whose size equals
        the recorded ``size``.  This is the only method that reads bytes, and
        it only reads the explicit ``object_path`` the caller supplies.  It
        never reads the quarantine root itself and never mutates anything.
        """

        entry = self.resolve_new_to_old(new_locator)
        object_path = _lexical_absolute(object_path)
        if object_path.is_symlink():
            raise ResolverError(
                "quarantine object must be a regular file, not a symlink: %s"
                % object_path
            )
        if not object_path.is_file():
            raise ResolverError("missing quarantine object: %s" % object_path)

        actual_hash = sha256_file(object_path)
        expected_hash = entry["destination_sha256"]
        if actual_hash != expected_hash:
            raise ResolverError(
                "object hash mismatch for %s: expected %s, got %s"
                % (object_path, expected_hash, actual_hash)
            )

        actual_size = object_path.stat().st_size
        if actual_size != entry["size"]:
            raise ResolverError(
                "object size mismatch for %s: expected %d, got %d"
                % (object_path, entry["size"], actual_size)
            )
        return {
            "new_locator": new_locator,
            "old_locator": entry["old_locator"],
            "source_sha256": entry["source_sha256"],
            "destination_sha256": expected_hash,
            "actual_sha256": actual_hash,
            "expected_size": entry["size"],
            "actual_size": actual_size,
            "verified": True,
        }

    def verify_live_source_against_entry(
        self,
        old_locator: str | os.PathLike[str],
        source_path: Path,
    ) -> Mapping[str, Any]:
        """Verify a live source file still matches its PATH_MAP entry.

        Used by the mutator immediately before a move/delete to prove the
        recorded source hash is still authoritative.  Read-only.
        """

        entry = self.resolve_old_to_new(old_locator)
        source_path = _lexical_absolute(source_path)
        if source_path.is_symlink():
            raise ResolverError(
                "live source must be a regular file, not a symlink: %s" % source_path
            )
        if not source_path.is_file():
            raise ResolverError("missing live source: %s" % source_path)

        actual_hash = sha256_file(source_path)
        if actual_hash != entry["source_sha256"]:
            raise ResolverError(
                "source hash drift for %s: expected %s, got %s"
                % (source_path, entry["source_sha256"], actual_hash)
            )
        actual_size = source_path.stat().st_size
        if actual_size != entry["size"]:
            raise ResolverError(
                "source size drift for %s: expected %d, got %d"
                % (source_path, entry["size"], actual_size)
            )
        return {
            "old_locator": str(_lexical_absolute(old_locator)),
            "new_locator": entry["new_locator"],
            "source_sha256": entry["source_sha256"],
            "actual_sha256": actual_hash,
            "expected_size": entry["size"],
            "actual_size": actual_size,
            "verified": True,
        }

    # -- restore planning -------------------------------------------------- #

    def build_restore_plan(
        self,
        quarantine_root: Path | None = None,
    ) -> Mapping[str, Any]:
        """Return a PURE restore plan for all quarantine_move entries.

        The plan describes, per entry, the source (quarantine object), the
        destination (old live locator), the expected hashes and sizes, and the
        recorded recovery command.  It does NOT execute any restore.  The
        caller (mutator, under explicit Codex apply gate) is responsible for
        performing the described copies and for all gates.

        ``quarantine_root`` may be supplied to override the PATH_MAP root for
        test fixtures that live in a temp directory.  When supplied it must be
        a raw absolute, traversal-free path that normalizes to EXACTLY the
        PATH_MAP quarantine root — no arbitrary root substitution is allowed.
        When omitted, the PATH_MAP root is used.
        """

        if quarantine_root is None:
            root = self._quarantine_root
        else:
            raw = os.fspath(quarantine_root)
            if not isinstance(raw, str) or not raw.strip():
                raise ResolverError("restore quarantine_root must be a non-empty path")
            if _has_traversal(raw):
                raise ResolverError(
                    "restore quarantine_root must not contain traversal: %s" % raw
                )
            if not os.path.isabs(raw):
                raise ResolverError(
                    "restore quarantine_root must be an absolute path, got %r" % raw
                )
            root = _lexical_absolute(raw)
            if root != self._quarantine_root:
                raise ResolverError(
                    "restore quarantine_root %s does not match PATH_MAP root %s"
                    % (root, self._quarantine_root)
                )

        steps: list[dict[str, Any]] = []
        for entry in self._entries:
            if entry["operation"] != OPERATION_QUARANTINE_MOVE:
                continue
            new_locator = entry["new_locator"]
            object_path = root / new_locator
            steps.append(
                {
                    "id": entry["id"],
                    "operation": "restore_move",
                    "source_locator": str(object_path),
                    "source_locator_relative": new_locator,
                    "destination_locator": entry["old_locator"],
                    "expected_sha256": entry["source_sha256"],
                    "expected_size": entry["size"],
                    "owner": entry["owner"],
                    "reason": entry["reason"],
                    "recovery_command": entry["recovery_command"],
                }
            )

        return {
            "plan_version": 1,
            "task_id": self.task_id,
            "quarantine_root": str(root),
            "operation": "restore",
            "step_count": len(steps),
            "steps": steps,
        }

    # -- idempotency helpers ----------------------------------------------- #

    def fingerprint(self) -> str:
        """Return a stable SHA-256 over the validated PATH_MAP content.

        Two calls on the same validated map (or a second resolver built from a
        byte-identical map) produce the same fingerprint, which lets the
        mutator prove a replay changes nothing.
        """

        material = {
            "schema_version": self._path_map["schema_version"],
            "task_id": self.task_id,
            "quarantine_root": str(self._quarantine_root),
            "expected_inventory_sha256": self.expected_inventory_sha256,
            "expected_protected_sha256": self.expected_protected_sha256,
            "entries": [
                {
                    "id": entry["id"],
                    "operation": entry["operation"],
                    "owner": entry["owner"],
                    "reason": entry["reason"],
                    "old_locator": entry["old_locator"],
                    "new_locator": entry["new_locator"],
                    "path_type": entry["path_type"],
                    "size": entry["size"],
                    "source_sha256": entry["source_sha256"],
                    "destination_sha256": entry["destination_sha256"],
                    "content_address": entry["content_address"],
                    "recovery_command": entry["recovery_command"],
                    "status": entry["status"],
                }
                for entry in self._entries
            ],
        }
        payload = json_dumpsCanonical(material)
        return _sha256_bytes(payload.encode("utf-8"))


# --------------------------------------------------------------------------- #
# Canonical JSON serialization (deterministic, UTF-8, no whitespace).
# --------------------------------------------------------------------------- #


def json_dumpsCanonical(value: Any) -> str:
    import json

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


# --------------------------------------------------------------------------- #
# PATH_MAP construction helper (tests / mutator use only).
# --------------------------------------------------------------------------- #


def content_address_for(source_sha256: str) -> PurePosixPath:
    """Return the quarantine objects path for a content hash."""

    digest = _sha256_hex(source_sha256)
    return PurePosixPath("objects") / digest[:2] / digest


def new_locator_for(source_sha256: str) -> str:
    """Return the quarantine-relative content-addressed locator string."""

    return content_address_for(source_sha256).as_posix()
