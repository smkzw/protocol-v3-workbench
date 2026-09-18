"""Ordered chapter draft candidate carrier for Protocol v3 V1 complete draft.

Purpose
-------
Provide an explicit ordered content-block candidate so a chapter draft can
preserve ``paragraph → table → paragraph → table`` object order and stable
identities.  Legacy :class:`~app.protocol_workflow.registries.chapters.ChapterSkillOutput`
groups ``facts`` / ``claims`` / ``evidence`` / ``objects`` and cannot recover
that order; :class:`~packages.contracts.workbench_contracts.protocol_v3.ContentObject.occurrences`
must never be expanded into fabricated instances.

Boundaries
----------
* Candidate only — not a confirmed
  :class:`~packages.contracts.workbench_contracts.protocol_v3.SemanticDocumentRevision`.
* Reuses :class:`~packages.contracts.workbench_contracts.StructuredTable` by
  type; does not redefine table/cell/note semantics.
* Evidence-ref checks only prove IDs appear in the caller-supplied
  ``known_evidence_ids`` universe.  That is **not** medical authenticity,
  admission, or quality scoring.
* Does not call models, storage, or routers; does not alter
  :class:`~app.protocol_workflow.registries.chapters.ChapterSkillOutput`.

Mutability
----------
Input :class:`StructuredTable` instances are detached (dump→validate) on
construction so later mutation of the caller's object does not rewrite the
recorded candidate.  Nested ``StructuredTable`` remains a mutable
``WorkbenchModel``; this module does **not** claim deep immutability of the
embedded table graph.

Subsequent interface suggestion (not implemented here)
------------------------------------------------------
When wiring V1 generation, add an optional ordered-blocks field alongside the
legacy ``ChapterSkillOutput`` payload (or a parallel candidate envelope) so
old checkers/fixtures keep consuming grouped objects while the new path emits
``OrderedChapterDraftCandidate``.  Adoption into ``SemanticDocumentRevision``
remains a separate confirm step that must supply real fact / evidence /
admission bindings — never auto-minted here.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.protocol_workflow.registries.chapters import ContentObject
from packages.contracts.workbench_contracts import StructuredTable
from packages.contracts.workbench_contracts.models import WorkbenchModel


class OrderedDraftBlockKind(str):
    """Block discriminator values for ordered draft candidates."""

    PARAGRAPH = "paragraph"
    TABLE = "table"


class OrderedDraftParagraphBlock(BaseModel):
    """One ordered paragraph candidate block."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    block_id: Annotated[str, Field(min_length=1)]
    kind: Literal["paragraph"] = OrderedDraftBlockKind.PARAGRAPH
    text: str
    source_locator: str = ""
    evidence_refs: tuple[str, ...] = ()

    @field_validator("evidence_refs")
    @classmethod
    def _unique_evidence_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("evidence_refs must not contain duplicates")
        if any(not ref for ref in value):
            raise ValueError("evidence_refs entries must be non-empty")
        return value


class OrderedDraftTableBlock(BaseModel):
    """One ordered table candidate block that reuses StructuredTable."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    block_id: Annotated[str, Field(min_length=1)]
    kind: Literal["table"] = OrderedDraftBlockKind.TABLE
    table: StructuredTable
    evidence_refs: tuple[str, ...] = ()

    @field_validator("evidence_refs")
    @classmethod
    def _unique_evidence_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("evidence_refs must not contain duplicates")
        if any(not ref for ref in value):
            raise ValueError("evidence_refs entries must be non-empty")
        return value

    @field_validator("table", mode="before")
    @classmethod
    def _detach_structured_table(cls, value: object) -> StructuredTable:
        """Record a detached StructuredTable copy; preserve original semantics."""
        if isinstance(value, StructuredTable):
            return StructuredTable.model_validate(value.model_dump(mode="python"))
        if isinstance(value, WorkbenchModel):
            return StructuredTable.model_validate(value.model_dump(mode="python"))
        return StructuredTable.model_validate(value)

    @model_validator(mode="after")
    def _table_block_identity_matches(self) -> OrderedDraftTableBlock:
        if self.table.block_id != self.block_id:
            raise ValueError(
                "table block_id identity mismatch: "
                f"enclosing block_id={self.block_id!r} "
                f"table.block_id={self.table.block_id!r}"
            )
        return self


OrderedDraftBlock = Annotated[
    Union[OrderedDraftParagraphBlock, OrderedDraftTableBlock],
    Field(discriminator="kind"),
]


class OrderedChapterDraftCandidate(BaseModel):
    """Ordered chapter draft candidate (not a confirmed semantic document)."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Literal["ordered_chapter_draft_candidate.v1"] = (
        "ordered_chapter_draft_candidate.v1"
    )
    chapter_contract_id: Annotated[str, Field(min_length=1)]
    node_id: Annotated[str, Field(min_length=1)]
    known_evidence_ids: tuple[str, ...] = ()
    blocks: tuple[OrderedDraftBlock, ...] = ()

    @field_validator("blocks", mode="before")
    @classmethod
    def _detach_blocks(cls, value):
        # Pydantic otherwise reuses already-validated block instances, including
        # their mutable StructuredTable children owned by a different candidate.
        return tuple(block.model_dump(mode="python") if isinstance(block, BaseModel)
                     else block for block in value)

    @field_validator("known_evidence_ids")
    @classmethod
    def _unique_known_evidence_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("known_evidence_ids must not contain duplicates")
        if any(not item for item in value):
            raise ValueError("known_evidence_ids entries must be non-empty")
        return value

    @model_validator(mode="after")
    def _validate_order_identity_and_refs(self) -> OrderedChapterDraftCandidate:
        block_ids = [block.block_id for block in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("ordered draft block_id values must be unique")

        table_ids = [
            block.table.table_id
            for block in self.blocks
            if isinstance(block, OrderedDraftTableBlock)
        ]
        if len(table_ids) != len(set(table_ids)):
            raise ValueError("ordered draft table_id values must be unique")

        known = set(self.known_evidence_ids)
        dangling: list[str] = []
        for block in self.blocks:
            for ref in block.evidence_refs:
                if ref not in known:
                    dangling.append(ref)
        if dangling:
            raise ValueError(
                "dangling evidence_refs not present in known_evidence_ids: "
                f"{sorted(set(dangling))!r} "
                "(ID-in-universe check only; not medical authenticity)"
            )
        return self


def refuse_occurrences_as_instances(obj: ContentObject) -> None:
    """Fail closed when a ContentObject.occurrences count is treated as instances.

    ``occurrences`` is a legacy obligation counter on
    :class:`~app.protocol_workflow.registries.chapters.ContentObject`.  It is
    not a list of concrete ordered objects.  Callers must supply explicit
    ordered blocks; this helper never expands ``occurrences`` into draft
    blocks.
    """
    if obj.occurrences != 0:
        raise ValueError(
            "cannot treat ContentObject.occurrences as ordered draft instances; "
            f"occurrences={obj.occurrences} object_kind={obj.object_kind!r}. "
            "Supply explicit OrderedDraftParagraphBlock / OrderedDraftTableBlock "
            "objects instead."
        )


__all__ = [
    "OrderedChapterDraftCandidate",
    "OrderedDraftBlock",
    "OrderedDraftBlockKind",
    "OrderedDraftParagraphBlock",
    "OrderedDraftTableBlock",
    "refuse_occurrences_as_instances",
]
