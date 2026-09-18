"""Read-only, exact-byte locator amendment; historical identities never change."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AMENDMENT_PATH = ROOT / "config/medical_writing/protocol_v3/authority_amendment_20260905.json"


def load_amendment():
    data = json.loads(AMENDMENT_PATH.read_text(encoding="utf-8"))
    frozen_path = ROOT / "tests/fixtures/protocol_v3/immutable_protected_assets.json"
    frozen_bytes = frozen_path.read_bytes()
    if hashlib.sha256(frozen_bytes).hexdigest() != data["frozen_manifest_sha256"]:
        raise ValueError("historical manifest hash mismatch")
    frozen = json.loads(frozen_bytes)
    expected = {a["path"]: a["sha256"] for a in frozen["assets"]
                if "cmss_sop_md_5101_protocol_template_authority" in a["rule_ids"]}
    if {r["old_locator"]: r["sha256"] for r in data["relocations"]} != expected:
        raise ValueError("relocation does not cover exact frozen authority")
    return data


def _verify_file(path, expected_hash):
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("absolute canonical locator required")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("symlink in authority locator")
    try:
        before = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        after = path.stat()
    except OSError as exc:
        raise ValueError("authority asset missing or unreadable") from exc
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size, after.st_mtime_ns, after.st_ino
    ) or digest != expected_hash:
        raise ValueError("authority asset hash mismatch: " + str(path))


def validate_amendment(data):
    old_root, new_root = Path(data["old_root"]), Path(data["new_root"])
    mapping = {}
    for row in data["relocations"]:
        old, new = Path(row["old_locator"]), Path(row["new_locator"])
        if (not row["owner"] or row["allowed"] != "read_only"
                or str(old) in mapping or new in mapping.values()
                or not old.is_relative_to(old_root)
                or not new.is_relative_to(new_root)
                or old.relative_to(old_root) != new.relative_to(new_root)):
            raise ValueError("invalid or duplicate relocation")
        _verify_file(new, row["sha256"])
        # A reappearing historical path must not silently shadow the amendment.
        if old.exists() or old.is_symlink():
            _verify_file(old, row["sha256"])
        mapping[str(old)] = new
    actual = {p for p in new_root.rglob("*") if p.suffix.casefold() in {".docx", ".xlsx"}}
    if actual != set(mapping.values()):
        raise ValueError("current authority tree contains missing or unknown assets")
    for row in data["additions"]:
        if not row["owner"] or row["allowed"] != "read_only":
            raise ValueError("new authority asset must have read-only owner")
        _verify_file(Path(row["path"]), row["sha256"])
    return mapping


def current_locators():
    return validate_amendment(load_amendment())
