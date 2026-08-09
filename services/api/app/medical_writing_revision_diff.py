"""Pure deterministic helpers for local medical-writing revision diffs."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from packages.contracts.workbench_contracts import RevisionDiffSegment
from packages.contracts.workbench_contracts.models import canonical_revision_diff_segments


@dataclass(frozen=True)
class RevisionDiffResult:
    source_hash: str
    proposal_hash: str
    segments: tuple[RevisionDiffSegment, ...]


def _text_hash(value: str) -> str:
    return sha256(str(value).encode("utf-8")).hexdigest()


def build_revision_diff(source_text: str, proposal_text: str) -> RevisionDiffResult:
    """Return a stable character-level diff without model/provider involvement.

    ``SequenceMatcher`` is configured with ``autojunk=False`` because protocol
    prose can contain repeated short tokens and the result must not depend on
    input length heuristics.  ``replace`` opcodes are emitted as delete then
    insert, which keeps each segment text tied to exactly one coordinate space.
    """

    source = str(source_text)
    proposal = str(proposal_text)
    segments = canonical_revision_diff_segments(source, proposal)

    # A zero-length/zero-change candidate is still a valid deterministic diff.
    # SequenceMatcher emits one equal opcode for equal strings, including two
    # empty strings, so no sentinel segment is needed.
    return RevisionDiffResult(
        source_hash=_text_hash(source),
        proposal_hash=_text_hash(proposal),
        segments=tuple(segments),
    )
