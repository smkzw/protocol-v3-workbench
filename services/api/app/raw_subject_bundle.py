from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Union


PathLike = Union[str, Path]

IMAGE_SUFFIXES = {
    ".bmp",
    ".gif",
    ".heic",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}


@dataclass(frozen=True)
class RawSubjectFile:
    path: str
    relative_path: str
    suffix: str
    size_bytes: int
    source_type: str
    needs_ocr_vlm: bool

    def as_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "relative_path": self.relative_path,
            "suffix": self.suffix,
            "size_bytes": self.size_bytes,
            "source_type": self.source_type,
            "needs_ocr_vlm": self.needs_ocr_vlm,
        }


@dataclass(frozen=True)
class RawSubjectBundleInventory:
    root_path: str
    files: List[RawSubjectFile]
    total_files: int
    source_type_counts: Dict[str, int]
    needs_ocr_vlm_count: int

    def as_dict(self) -> Dict[str, object]:
        return {
            "root_path": self.root_path,
            "files": [file.as_dict() for file in self.files],
            "total_files": self.total_files,
            "source_type_counts": dict(self.source_type_counts),
            "needs_ocr_vlm_count": self.needs_ocr_vlm_count,
        }


def source_type_for_suffix(suffix: str) -> str:
    normalized = (suffix or "").lower()
    if normalized == ".pdf":
        return "pdf"
    if normalized == ".doc":
        return "doc"
    if normalized == ".docx":
        return "docx"
    if normalized in IMAGE_SUFFIXES:
        return "image"
    if normalized == ".zip":
        return "zip"
    return "other"


def needs_ocr_vlm_for_source_type(source_type: str) -> bool:
    return source_type in {"pdf", "image"}


def inventory_subject_bundle(root_path: PathLike) -> RawSubjectBundleInventory:
    root = Path(root_path).expanduser()
    if not root.exists():
        raise FileNotFoundError(str(root))
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    root_resolved = root.resolve()
    files: List[RawSubjectFile] = []
    for file_path in sorted(root_resolved.rglob("*"), key=lambda path: _relative_sort_key(root_resolved, path)):
        if not _is_inventory_file(root_resolved, file_path):
            continue
        suffix = file_path.suffix.lower()
        source_type = source_type_for_suffix(suffix)
        needs_ocr_vlm = needs_ocr_vlm_for_source_type(source_type)
        stat = file_path.stat()
        files.append(
            RawSubjectFile(
                path=str(file_path),
                relative_path=file_path.relative_to(root_resolved).as_posix(),
                suffix=suffix,
                size_bytes=stat.st_size,
                source_type=source_type,
                needs_ocr_vlm=needs_ocr_vlm,
            )
        )

    source_type_counts = dict(Counter(file.source_type for file in files))
    return RawSubjectBundleInventory(
        root_path=str(root_resolved),
        files=files,
        total_files=len(files),
        source_type_counts=source_type_counts,
        needs_ocr_vlm_count=sum(1 for file in files if file.needs_ocr_vlm),
    )


def _is_inventory_file(root: Path, path: Path) -> bool:
    if not path.is_file():
        return False
    relative_parts = path.relative_to(root).parts
    if any(part.startswith(".") or part == "__MACOSX" for part in relative_parts):
        return False
    return not path.name.startswith("~$")


def _relative_sort_key(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix().lower()
    except ValueError:
        return path.as_posix().lower()
