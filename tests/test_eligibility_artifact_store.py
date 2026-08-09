from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.api.app.eligibility_artifact_store import (
    ArtifactAlreadyExistsError,
    ArtifactIntegrityError,
    EligibilityArtifactStore,
    InvalidStorageKeyError,
)


class EligibilityArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name) / "controlled-artifacts"
        self.store = EligibilityArtifactStore(self.root)

    def test_write_and_verified_read_return_integrity_metadata(self) -> None:
        body = b'{"page":1,"text":"controlled evidence"}'

        artifact = self.store.write(
            "proj_d001/SA07005/eligjob-001/page-001.json",
            body,
            "application/json",
        )

        self.assertEqual(64, len(artifact.content_hash))
        self.assertEqual(len(body), artifact.size_bytes)
        self.assertEqual("application/json", artifact.media_type)
        self.assertEqual(body, self.store.read(artifact))
        self.assertEqual(
            body,
            self.store.read(
                artifact.storage_key,
                expected_hash=artifact.content_hash,
                expected_size_bytes=artifact.size_bytes,
            ),
        )

    def test_public_projection_excludes_internal_locator_body_root_and_full_hash(
        self,
    ) -> None:
        body = b"private patient evidence"
        artifact = self.store.write(
            "proj_d001/SA07005/private-evidence.txt", body, "text/plain"
        )

        public = artifact.public_dict()
        serialized = json.dumps(public, sort_keys=True)

        self.assertEqual("private-evidence.txt", public["filename"])
        self.assertEqual(len(body), public["size_bytes"])
        self.assertNotIn("storage_key", public)
        self.assertNotIn("content_hash", public)
        self.assertNotIn(artifact.storage_key, serialized)
        self.assertNotIn(artifact.content_hash, serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn(body.decode(), serialized)

    def test_rejects_non_relative_or_non_canonical_storage_keys(self) -> None:
        invalid_keys = (
            "",
            ".",
            "..",
            "/absolute/file.json",
            "../escape.json",
            "project/../../escape.json",
            "project/./file.json",
            "project//file.json",
            "project/",
            "C:\\absolute\\file.json",
            "project\\..\\escape.json",
            "project/\x00file.json",
        )

        for storage_key in invalid_keys:
            with self.subTest(storage_key=storage_key):
                with self.assertRaises(InvalidStorageKeyError):
                    self.store.write(storage_key, b"body", "application/json")

    def test_rejects_symlinked_parent_that_escapes_root(self) -> None:
        outside = Path(self.temp_dir.name) / "outside"
        outside.mkdir()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "linked").symlink_to(outside, target_is_directory=True)

        with self.assertRaises(InvalidStorageKeyError):
            self.store.write("linked/escape.txt", b"must not escape", "text/plain")

        self.assertFalse((outside / "escape.txt").exists())

    def test_rejects_symlink_target_on_read(self) -> None:
        outside = Path(self.temp_dir.name) / "outside.txt"
        outside.write_bytes(b"outside")
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "linked.txt").symlink_to(outside)

        with self.assertRaises(InvalidStorageKeyError):
            self.store.read("linked.txt", expected_hash="0" * 64, expected_size_bytes=7)

    def test_existing_artifact_is_never_overwritten(self) -> None:
        first = self.store.write("immutable.txt", b"first", "text/plain")

        with self.assertRaises(ArtifactAlreadyExistsError):
            self.store.write("immutable.txt", b"second", "text/plain")

        self.assertEqual(b"first", self.store.read(first))

    def test_interrupted_write_leaves_no_target_or_temporary_file(self) -> None:
        with patch(
            "services.api.app.eligibility_artifact_store._write_all",
            side_effect=OSError("injected write failure"),
        ):
            with self.assertRaises(OSError):
                self.store.write(
                    "nested/interrupted.bin", b"body", "application/octet-stream"
                )

        self.assertFalse((self.root / "nested" / "interrupted.bin").exists())
        self.assertEqual([], list(self.root.rglob(".eligibility-artifact-*")))

    def test_directory_sync_failure_rolls_back_published_target(self) -> None:
        with patch(
            "services.api.app.eligibility_artifact_store.os.fsync",
            side_effect=(None, OSError("injected directory sync failure")),
        ):
            with self.assertRaises(OSError):
                self.store.write("sync-failed.bin", b"body", "application/octet-stream")

        self.assertFalse((self.root / "sync-failed.bin").exists())
        self.assertEqual([], list(self.root.rglob(".eligibility-artifact-*")))

    def test_read_fails_closed_after_content_tampering(self) -> None:
        artifact = self.store.write("tampered.txt", b"trusted", "text/plain")
        (self.root / artifact.storage_key).write_bytes(b"changed")

        with self.assertRaises(ArtifactIntegrityError):
            self.store.read(artifact)

    def test_read_fails_closed_after_size_tampering(self) -> None:
        artifact = self.store.write("resized.txt", b"trusted", "text/plain")
        (self.root / artifact.storage_key).write_bytes(b"trusted-with-extra-data")

        with self.assertRaises(ArtifactIntegrityError):
            self.store.read(artifact)

    def test_read_requires_complete_expected_integrity_metadata(self) -> None:
        artifact = self.store.write("required.txt", b"trusted", "text/plain")

        with self.assertRaises(ValueError):
            self.store.read(artifact.storage_key)
        with self.assertRaises(ValueError):
            self.store.read(artifact.storage_key, expected_hash=artifact.content_hash)
        with self.assertRaises(ValueError):
            self.store.read(
                artifact.storage_key,
                expected_hash="not-a-sha256",
                expected_size_bytes=artifact.size_bytes,
            )


if __name__ == "__main__":
    unittest.main()
