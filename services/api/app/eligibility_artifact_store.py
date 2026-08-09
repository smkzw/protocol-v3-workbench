from __future__ import annotations

import errno
import hashlib
import hmac
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, Optional, Tuple, Union


_SHA256_HEX_LENGTH = 64
_READ_CHUNK_SIZE = 1024 * 1024
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class EligibilityArtifactStoreError(Exception):
    """Base error for controlled eligibility artifact storage."""


class InvalidStorageKeyError(ValueError, EligibilityArtifactStoreError):
    """The storage key is invalid or cannot be confined to the artifact root."""


class ArtifactAlreadyExistsError(FileExistsError, EligibilityArtifactStoreError):
    """An immutable artifact already exists for the requested storage key."""


class ArtifactIntegrityError(IOError, EligibilityArtifactStoreError):
    """Stored content does not match its required integrity metadata."""


@dataclass(frozen=True)
class EligibilityArtifactMetadata:
    storage_key: str
    content_hash: str
    size_bytes: int
    media_type: str

    def public_dict(self) -> Dict[str, Any]:
        return {
            "filename": PurePosixPath(self.storage_key).name,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "integrity_verified": True,
        }


EligibilityArtifact = EligibilityArtifactMetadata


def _write_all(fd: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("artifact write made no progress")
        view = view[written:]


class EligibilityArtifactStore:
    """Immutable file store confined beneath one workbench-controlled root."""

    def __init__(self, root: Union[str, Path]):
        root_path = Path(root).expanduser()
        root_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._root = root_path.resolve(strict=True)
        if not self._root.is_dir():
            raise ValueError("artifact root must be a directory")
        if not _NOFOLLOW or not _DIRECTORY:
            raise RuntimeError("platform lacks required no-follow directory support")

    def write(
        self,
        storage_key: str,
        content: Union[bytes, bytearray, memoryview],
        media_type: str,
    ) -> EligibilityArtifactMetadata:
        parts = self._validate_storage_key(storage_key)
        body = self._validate_content(content)
        normalized_media_type = self._validate_media_type(media_type)
        content_hash = hashlib.sha256(body).hexdigest()
        parent_fd, filename = self._open_parent(parts, create=True)
        temp_name = ".eligibility-artifact-{}".format(secrets.token_hex(16))
        temp_created = False
        temp_fd: Optional[int] = None
        target_published = False
        write_completed = False

        try:
            temp_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC,
                0o600,
                dir_fd=parent_fd,
            )
            temp_created = True
            _write_all(temp_fd, body)
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = None

            try:
                os.link(
                    temp_name,
                    filename,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                target_published = True
            except FileExistsError as exc:
                raise ArtifactAlreadyExistsError(
                    "artifact storage key already exists"
                ) from exc

            os.unlink(temp_name, dir_fd=parent_fd)
            temp_created = False
            os.fsync(parent_fd)
            write_completed = True
        finally:
            if temp_fd is not None:
                os.close(temp_fd)
            if temp_created:
                try:
                    os.unlink(temp_name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
            if target_published and not write_completed:
                try:
                    os.unlink(filename, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
            os.close(parent_fd)

        return EligibilityArtifactMetadata(
            storage_key=storage_key,
            content_hash=content_hash,
            size_bytes=len(body),
            media_type=normalized_media_type,
        )

    def write_bytes(
        self,
        storage_key: str,
        content: Union[bytes, bytearray, memoryview],
        media_type: str,
    ) -> EligibilityArtifactMetadata:
        return self.write(storage_key, content, media_type)

    def read(
        self,
        artifact: Union[EligibilityArtifactMetadata, str],
        *,
        expected_hash: Optional[str] = None,
        expected_size_bytes: Optional[int] = None,
    ) -> bytes:
        if isinstance(artifact, EligibilityArtifactMetadata):
            storage_key = artifact.storage_key
            expected_hash = (
                artifact.content_hash if expected_hash is None else expected_hash
            )
            expected_size_bytes = (
                artifact.size_bytes
                if expected_size_bytes is None
                else expected_size_bytes
            )
        elif isinstance(artifact, str):
            storage_key = artifact
        else:
            raise TypeError("artifact must be eligibility metadata or a storage key")

        normalized_hash = self._validate_expected_hash(expected_hash)
        normalized_size = self._validate_expected_size(expected_size_bytes)
        parts = self._validate_storage_key(storage_key)
        parent_fd, filename = self._open_parent(parts, create=False)
        file_fd: Optional[int] = None

        try:
            try:
                file_fd = os.open(
                    filename,
                    os.O_RDONLY | _NOFOLLOW | _CLOEXEC,
                    dir_fd=parent_fd,
                )
            except OSError as exc:
                self._raise_path_error(exc)

            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode):
                raise InvalidStorageKeyError("artifact target must be a regular file")
            if before.st_size != normalized_size:
                raise ArtifactIntegrityError("artifact size verification failed")

            digest = hashlib.sha256()
            chunks = []
            size = 0
            while True:
                chunk = os.read(file_fd, _READ_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
                chunks.append(chunk)
                size += len(chunk)

            after = os.fstat(file_fd)
            if (
                size != normalized_size
                or after.st_size != normalized_size
                or before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
            ):
                raise ArtifactIntegrityError("artifact size verification failed")
            if not hmac.compare_digest(digest.hexdigest(), normalized_hash):
                raise ArtifactIntegrityError("artifact hash verification failed")
            return b"".join(chunks)
        finally:
            if file_fd is not None:
                os.close(file_fd)
            os.close(parent_fd)

    def read_bytes(
        self,
        storage_key: str,
        *,
        expected_hash: str,
        expected_size_bytes: int,
    ) -> bytes:
        return self.read(
            storage_key,
            expected_hash=expected_hash,
            expected_size_bytes=expected_size_bytes,
        )

    @staticmethod
    def _validate_storage_key(storage_key: str) -> Tuple[str, ...]:
        if not isinstance(storage_key, str):
            raise InvalidStorageKeyError("storage key must be a string")
        if not storage_key or "\x00" in storage_key or "\\" in storage_key:
            raise InvalidStorageKeyError(
                "storage key must be a canonical relative path"
            )
        if PurePosixPath(storage_key).is_absolute():
            raise InvalidStorageKeyError("absolute storage keys are not allowed")
        windows_path = PureWindowsPath(storage_key)
        if windows_path.is_absolute() or windows_path.drive:
            raise InvalidStorageKeyError("absolute storage keys are not allowed")

        raw_parts = storage_key.split("/")
        if any(part in ("", ".", "..") for part in raw_parts):
            raise InvalidStorageKeyError(
                "storage key must be a canonical relative path"
            )
        return tuple(raw_parts)

    @staticmethod
    def _validate_content(content: Union[bytes, bytearray, memoryview]) -> bytes:
        if not isinstance(content, (bytes, bytearray, memoryview)):
            raise TypeError("artifact content must be bytes-like")
        return bytes(content)

    @staticmethod
    def _validate_media_type(media_type: str) -> str:
        if not isinstance(media_type, str) or not media_type.strip():
            raise ValueError("media_type is required")
        normalized = media_type.strip()
        if any(ord(character) < 32 for character in normalized):
            raise ValueError("media_type contains control characters")
        return normalized

    @staticmethod
    def _validate_expected_hash(expected_hash: Optional[str]) -> str:
        if not isinstance(expected_hash, str):
            raise ValueError("expected SHA-256 hash is required")
        normalized = expected_hash.lower()
        if len(normalized) != _SHA256_HEX_LENGTH:
            raise ValueError("expected hash must be a complete SHA-256 hex digest")
        try:
            bytes.fromhex(normalized)
        except ValueError as exc:
            raise ValueError(
                "expected hash must be a complete SHA-256 hex digest"
            ) from exc
        return normalized

    @staticmethod
    def _validate_expected_size(expected_size_bytes: Optional[int]) -> int:
        if (
            not isinstance(expected_size_bytes, int)
            or isinstance(expected_size_bytes, bool)
            or expected_size_bytes < 0
        ):
            raise ValueError("expected_size_bytes is required and must be non-negative")
        return expected_size_bytes

    def _open_parent(self, parts: Tuple[str, ...], *, create: bool) -> Tuple[int, str]:
        current_fd = os.open(
            str(self._root), os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC
        )
        try:
            for part in parts[:-1]:
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                try:
                    child_fd = os.open(
                        part,
                        os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                        dir_fd=current_fd,
                    )
                except OSError as exc:
                    self._raise_path_error(exc)
                os.close(current_fd)
                current_fd = child_fd
            return current_fd, parts[-1]
        except Exception:
            os.close(current_fd)
            raise

    @staticmethod
    def _raise_path_error(exc: OSError) -> None:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise InvalidStorageKeyError(
                "storage key crosses a symlink or non-directory path"
            ) from exc
        if exc.errno == errno.ENOENT:
            raise FileNotFoundError("artifact storage key was not found") from exc
        raise exc
