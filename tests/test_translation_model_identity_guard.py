from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_ROOTS = (
    ROOT / "services",
    ROOT / "packages",
    ROOT / "frontend" / "src",
    ROOT / "frontend" / "dist",
    ROOT / "scripts",
    ROOT / "tests",
    ROOT / "runtime",
    ROOT / "config",
    ROOT / "deploy",
)
CURRENT_RUNTIME_EVIDENCE = (
    ROOT / "evidence" / "independent_ai" / "role_status_resume_20260726.json",
)
IGNORED_PARTS = {
    "__pycache__",
    "node_modules",
}
TEXT_SUFFIXES = {
    ".css",
    ".env",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
    ".zsh",
}
INVALID_TRANSLATION_ALIAS = re.compile(
    "hy" + r"[-_ ]?mt-?" + "3",
    re.IGNORECASE,
)


def _active_text_files():
    for root in ACTIVE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if (
                path.is_file()
                and path.suffix.lower() in TEXT_SUFFIXES
                and not IGNORED_PARTS.intersection(path.parts)
                and path != Path(__file__)
            ):
                yield path
    yield from (path for path in CURRENT_RUNTIME_EVIDENCE if path.is_file())


def test_active_product_tree_uses_only_hy_mt2_identity():
    offenders = []
    for path in _active_text_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if INVALID_TRANSLATION_ALIAS.search(text):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == [], (
        "The writing product contains an invalid translation-model alias. "
        "It must use the runtime-gated Hy-MT2 body translator. Offenders: "
        + ", ".join(offenders)
    )
