from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .protocol_text_extractor import (
    ProtocolParagraph,
    ProtocolTextDocument,
    parse_protocol_docx,
)


PathLike = Union[str, Path]
RuleKey = Tuple[str, int, str, str]

_SECTION_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.、]?\s*)?(?:受试者)?(入选标准|排除标准)\s*[：:]?\s*$"
)
_INLINE_CHILD_RE = re.compile(
    r"^\s*(?:[A-Za-z]|[（(]?[一二三四五六七八九十0-9]+[）)])\s*[)）.、]\s*"
)
_HEADING_STYLE_TOKENS = ("heading", "标题")
_RULE_EXTRACTOR_VERSION = "eligibility_protocol_rules_v1"
_CONFIRMED_NUMBERING_TEMPLATES = {"%1", "%1.", "%1、"}


@dataclass(frozen=True)
class EligibilityProtocolProjectConfig:
    project_id: str
    aliases: Tuple[str, ...]
    protocol_path: PathLike
    source_entry: str
    source_version: str


@dataclass(frozen=True)
class EligibilityProtocolRule:
    project_id: str
    criterion_uid: str
    rule_revision: str
    review_rule_id: str
    source_rule_label: Optional[str]
    numbering_status: str
    criterion_type: str
    text: str
    source_locator: str
    source_entry: str
    source_version: str
    content_hash: str
    word_num_id: Optional[str]
    word_ilvl: Optional[int]
    numbering_format: str
    numbering_level_text: str
    children: Tuple["EligibilityProtocolRule", ...] = ()

    @property
    def rule_id(self) -> str:
        """Compatibility alias for the system-generated review identifier."""
        return self.review_rule_id

    def public_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "criterion_uid": self.criterion_uid,
            "rule_revision": self.rule_revision,
            "review_rule_id": self.review_rule_id,
            "rule_id": self.review_rule_id,
            "source_rule_label": self.source_rule_label,
            "numbering_status": self.numbering_status,
            "criterion_type": self.criterion_type,
            "text": self.text,
            "source_locator": self.source_locator,
            "source_entry": self.source_entry,
            "source_version": self.source_version,
            "children": [child.public_dict() for child in self.children],
        }


@dataclass(frozen=True)
class EligibilityProtocolRuleSection:
    criterion_type: str
    heading_text: str
    source_locator: str
    source_entry: str
    source_version: str
    content_hash: str
    rules: Tuple[EligibilityProtocolRule, ...]

    def public_dict(self) -> Dict[str, Any]:
        return {
            "criterion_type": self.criterion_type,
            "heading_text": self.heading_text,
            "source_locator": self.source_locator,
            "source_entry": self.source_entry,
            "source_version": self.source_version,
            "rules": [rule.public_dict() for rule in self.rules],
        }


@dataclass(frozen=True)
class EligibilityProtocolRuleSet:
    project_id: str
    rule_revision: str
    source_entry: str
    source_version: str
    content_hash: str
    inclusion: EligibilityProtocolRuleSection
    exclusion: EligibilityProtocolRuleSection

    def public_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "rule_revision": self.rule_revision,
            "source_entry": self.source_entry,
            "source_version": self.source_version,
            "counts": {
                "inclusion": len(self.inclusion.rules),
                "exclusion": len(self.exclusion.rules),
            },
            "inclusion": self.inclusion.public_dict(),
            "exclusion": self.exclusion.public_dict(),
        }


ELIGIBILITY_PROTOCOL_MANIFEST_ENV = (
    "MEDICAL_WORKBENCH_ELIGIBILITY_PROTOCOL_MANIFEST"
)
DEFAULT_ELIGIBILITY_PROTOCOL_CONFIGS: Tuple[
    EligibilityProtocolProjectConfig, ...
] = ()


@dataclass
class _RuleBuilder:
    paragraph: ProtocolParagraph
    children: List["_RuleBuilder"] = field(default_factory=list)


class EligibilityProtocolRuleService:
    """Read-only extraction of project-scoped IN/EX trees from original DOCX files."""

    def __init__(
        self,
        configs: Optional[
            Sequence[EligibilityProtocolProjectConfig]
        ] = None,
        *,
        manifest_path: Optional[PathLike] = None,
    ) -> None:
        if configs is not None and manifest_path is not None:
            raise ValueError(
                "provide eligibility protocol configs or manifest_path, not both"
            )
        if configs is None:
            configured_manifest = manifest_path or os.environ.get(
                ELIGIBILITY_PROTOCOL_MANIFEST_ENV,
                "",
            )
            configs = (
                load_eligibility_protocol_configs(configured_manifest)
                if configured_manifest
                else DEFAULT_ELIGIBILITY_PROTOCOL_CONFIGS
            )
        self._configs_by_alias: Dict[str, EligibilityProtocolProjectConfig] = {}
        for config in configs:
            aliases = (config.project_id, *config.aliases)
            for alias in aliases:
                normalized = _normalize_project_id(alias)
                existing = self._configs_by_alias.get(normalized)
                if existing is not None and existing != config:
                    raise ValueError(f"duplicate eligibility protocol project alias: {alias}")
                self._configs_by_alias[normalized] = config

    def rules_for_project(self, project_id: str) -> EligibilityProtocolRuleSet:
        normalized = _normalize_project_id(project_id)
        if not normalized:
            raise ValueError("project_id is required")
        try:
            config = self._configs_by_alias[normalized]
        except KeyError as exc:
            raise KeyError(f"eligibility protocol project is not configured: {project_id}") from exc

        path = Path(config.protocol_path)
        content = path.read_bytes()
        document = parse_protocol_docx(path.name, content)
        inclusion_index, exclusion_index = _find_canonical_section_headings(document)
        exclusion_end = _next_peer_heading_index(
            document.paragraphs,
            exclusion_index,
        )
        inclusion_builders = _section_rule_builders(
            document.paragraphs[inclusion_index + 1 : exclusion_index]
        )
        exclusion_builders = _section_rule_builders(
            document.paragraphs[exclusion_index + 1 : exclusion_end]
        )
        rule_revision = _rule_revision(
            config,
            document.source_hash,
            inclusion_builders,
            exclusion_builders,
        )

        inclusion = _build_section(
            config,
            document,
            "inclusion",
            inclusion_index,
            "IN",
            inclusion_builders,
            rule_revision,
        )
        exclusion = _build_section(
            config,
            document,
            "exclusion",
            exclusion_index,
            "EX",
            exclusion_builders,
            rule_revision,
        )
        return EligibilityProtocolRuleSet(
            project_id=config.project_id,
            rule_revision=rule_revision,
            source_entry=config.source_entry,
            source_version=config.source_version,
            content_hash=document.source_hash,
            inclusion=inclusion,
            exclusion=exclusion,
        )


def load_eligibility_protocol_configs(
    manifest_path: PathLike,
) -> Tuple[EligibilityProtocolProjectConfig, ...]:
    path = Path(manifest_path).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(
            "eligibility protocol source manifest does not exist"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            "eligibility protocol source manifest is not valid JSON"
        ) from exc
    projects = payload.get("projects") if isinstance(payload, dict) else payload
    if not isinstance(projects, list):
        raise ValueError(
            "eligibility protocol source manifest must contain a projects list"
        )
    configs: list[EligibilityProtocolProjectConfig] = []
    for index, item in enumerate(projects):
        if not isinstance(item, dict):
            raise ValueError(
                f"eligibility protocol project #{index + 1} must be an object"
            )
        project_id = str(item.get("project_id") or "").strip()
        protocol_path = str(item.get("protocol_path") or "").strip()
        source_entry = str(item.get("source_entry") or "").strip()
        source_version = str(item.get("source_version") or "").strip()
        if not all(
            (project_id, protocol_path, source_entry, source_version)
        ):
            raise ValueError(
                "eligibility protocol manifest project requires "
                "project_id, protocol_path, source_entry and source_version"
            )
        aliases_value = item.get("aliases") or []
        if not isinstance(aliases_value, list):
            raise ValueError(
                "eligibility protocol project aliases must be a list"
            )
        configs.append(
            EligibilityProtocolProjectConfig(
                project_id=project_id,
                aliases=tuple(
                    str(alias).strip()
                    for alias in aliases_value
                    if str(alias).strip()
                ),
                protocol_path=Path(protocol_path).expanduser(),
                source_entry=source_entry,
                source_version=source_version,
            )
        )
    return tuple(configs)


def _normalize_project_id(project_id: str) -> str:
    return project_id.strip().lower()


def _find_canonical_section_headings(document: ProtocolTextDocument) -> Tuple[int, int]:
    candidates: List[Tuple[int, str]] = []
    for index, paragraph in enumerate(document.paragraphs):
        match = _SECTION_HEADING_RE.fullmatch(paragraph.text)
        if match is None or not _is_body_heading(paragraph):
            continue
        candidates.append((index, "inclusion" if match.group(1) == "入选标准" else "exclusion"))

    scored_pairs: List[Tuple[int, int, int]] = []
    for inclusion_index, kind in candidates:
        if kind != "inclusion":
            continue
        exclusion_index = next(
            (
                index
                for index, candidate_kind in candidates
                if index > inclusion_index and candidate_kind == "exclusion"
            ),
            None,
        )
        if exclusion_index is None:
            continue
        if (
            document.paragraphs[inclusion_index].outline_level
            != document.paragraphs[exclusion_index].outline_level
        ):
            continue
        exclusion_end = _next_peer_heading_index(document.paragraphs, exclusion_index)
        try:
            inclusion_key = _select_top_level_key(
                document.paragraphs[inclusion_index + 1 : exclusion_index]
            )
            exclusion_key = _select_top_level_key(
                document.paragraphs[exclusion_index + 1 : exclusion_end]
            )
        except ValueError:
            continue
        score = _key_count(
            document.paragraphs[inclusion_index + 1 : exclusion_index], inclusion_key
        ) + _key_count(
            document.paragraphs[exclusion_index + 1 : exclusion_end], exclusion_key
        )
        scored_pairs.append((score, inclusion_index, exclusion_index))

    if not scored_pairs:
        raise ValueError("canonical body inclusion/exclusion sections were not found")
    highest_score = max(item[0] for item in scored_pairs)
    best_pairs = [item for item in scored_pairs if item[0] == highest_score]
    if len(best_pairs) != 1:
        raise ValueError("ambiguous body inclusion/exclusion sections were found")
    _, inclusion_index, exclusion_index = best_pairs[0]
    return inclusion_index, exclusion_index


def _is_body_heading(paragraph: ProtocolParagraph) -> bool:
    if paragraph.is_in_table:
        return False
    style_name = paragraph.style_name.strip().lower()
    if style_name.startswith("toc"):
        return False
    return paragraph.outline_level is not None or any(
        token in style_name for token in _HEADING_STYLE_TOKENS
    )


def _next_peer_heading_index(
    paragraphs: Sequence[ProtocolParagraph],
    heading_index: int,
) -> int:
    heading = paragraphs[heading_index]
    heading_level = heading.outline_level
    for index in range(heading_index + 1, len(paragraphs)):
        paragraph = paragraphs[index]
        if paragraph.is_in_table or paragraph.outline_level is None:
            continue
        if heading_level is None or paragraph.outline_level <= heading_level:
            return index
    return len(paragraphs)


def _build_section(
    config: EligibilityProtocolProjectConfig,
    document: ProtocolTextDocument,
    criterion_type: str,
    heading_index: int,
    rule_prefix: str,
    top_rules: Sequence[_RuleBuilder],
    rule_revision: str,
) -> EligibilityProtocolRuleSection:
    heading = document.paragraphs[heading_index]
    frozen_rules = tuple(
        _freeze_rule(
            builder,
            config,
            criterion_type,
            document.source_hash,
            f"{rule_prefix}-{index:02d}",
            rule_revision,
            source_sequence_index=index,
        )
        for index, builder in enumerate(top_rules, start=1)
    )
    return EligibilityProtocolRuleSection(
        criterion_type=criterion_type,
        heading_text=heading.text,
        source_locator=heading.source_locator,
        source_entry=config.source_entry,
        source_version=config.source_version,
        content_hash=document.source_hash,
        rules=frozen_rules,
    )


def _section_rule_builders(paragraphs: Sequence[ProtocolParagraph]) -> List[_RuleBuilder]:
    top_key = _select_top_level_key(paragraphs)
    return _build_rule_tree(paragraphs, top_key)


def _rule_revision(
    config: EligibilityProtocolProjectConfig,
    content_hash: str,
    inclusion: Sequence[_RuleBuilder],
    exclusion: Sequence[_RuleBuilder],
) -> str:
    canonical_tree = {
        "inclusion": [_canonical_rule_node(node) for node in inclusion],
        "exclusion": [_canonical_rule_node(node) for node in exclusion],
    }
    digest = hashlib.sha256()
    for value in (
        "eligibility-rule-revision",
        _normalize_project_id(config.project_id),
        content_hash,
        _RULE_EXTRACTOR_VERSION,
        json.dumps(canonical_tree, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return f"eligrulev_{digest.hexdigest()[:24]}"


def _canonical_rule_node(builder: _RuleBuilder) -> Dict[str, Any]:
    paragraph = builder.paragraph
    return {
        "locator": paragraph.source_locator,
        "text": _normalize_criterion_text(paragraph.text),
        "ilvl": paragraph.ilvl,
        "numbering_format": paragraph.numbering_format,
        "numbering_level_text": paragraph.numbering_level_text,
        "numbering_start": paragraph.numbering_start,
        "numbering_start_override": paragraph.numbering_start_override,
        "children": [_canonical_rule_node(child) for child in builder.children],
    }


def _select_top_level_key(paragraphs: Sequence[ProtocolParagraph]) -> RuleKey:
    keys = [
        key
        for paragraph in paragraphs
        if not paragraph.is_in_table
        if (key := _rule_key(paragraph)) is not None
        and paragraph.numbering_format == "decimal"
        and paragraph.ilvl == 0
    ]
    if not keys:
        raise ValueError("numbered top-level eligibility rules were not found")
    counts = Counter(keys)
    first_index = {key: keys.index(key) for key in counts}
    return max(counts, key=lambda key: (counts[key], -first_index[key]))


def _key_count(paragraphs: Sequence[ProtocolParagraph], key: RuleKey) -> int:
    return sum(_rule_key(paragraph) == key for paragraph in paragraphs)


def _rule_key(paragraph: ProtocolParagraph) -> Optional[RuleKey]:
    if paragraph.num_id is None or paragraph.ilvl is None:
        return None
    return (
        paragraph.num_id,
        paragraph.ilvl,
        paragraph.numbering_format,
        paragraph.numbering_level_text,
    )


def _build_rule_tree(
    paragraphs: Sequence[ProtocolParagraph],
    top_key: RuleKey,
) -> List[_RuleBuilder]:
    roots: List[_RuleBuilder] = []
    stack: Dict[int, _RuleBuilder] = {}
    key_depths: Dict[RuleKey, int] = {top_key: 0}
    last_depth = 0
    unnumbered_depth: Optional[int] = None

    for paragraph in paragraphs:
        if paragraph.is_in_table:
            continue
        key = _rule_key(paragraph)
        if key == top_key:
            builder = _RuleBuilder(paragraph=paragraph)
            roots.append(builder)
            stack = {0: builder}
            last_depth = 0
            unnumbered_depth = None
            continue
        if not roots:
            continue

        depth = _child_depth(
            paragraph,
            key,
            top_key,
            key_depths,
            stack,
            last_depth,
            unnumbered_depth,
        )
        if key is None:
            unnumbered_depth = depth
        else:
            unnumbered_depth = None
            key_depths.setdefault(key, depth)

        parent_depth = max(candidate for candidate in stack if candidate < depth)
        builder = _RuleBuilder(paragraph=paragraph)
        stack[parent_depth].children.append(builder)
        stack = {candidate: node for candidate, node in stack.items() if candidate < depth}
        stack[depth] = builder
        last_depth = depth

    return roots


def _child_depth(
    paragraph: ProtocolParagraph,
    key: Optional[RuleKey],
    top_key: RuleKey,
    key_depths: Dict[RuleKey, int],
    stack: Dict[int, _RuleBuilder],
    last_depth: int,
    unnumbered_depth: Optional[int],
) -> int:
    if key is not None and key in key_depths:
        return max(1, key_depths[key])
    if key is not None and key[0] == top_key[0] and key[1] > top_key[1]:
        return key[1] - top_key[1]

    last_node = stack[last_depth]
    if key is None:
        if _INLINE_CHILD_RE.match(paragraph.text):
            return 1
        if unnumbered_depth is not None:
            return unnumbered_depth
        if _introduces_children(last_node.paragraph.text):
            return last_depth + 1
        return max(1, last_depth)

    if _introduces_children(last_node.paragraph.text):
        return last_depth + 1
    return 1


def _introduces_children(text: str) -> bool:
    return text.rstrip().endswith((":", "："))


def _freeze_rule(
    builder: _RuleBuilder,
    config: EligibilityProtocolProjectConfig,
    criterion_type: str,
    content_hash: str,
    review_rule_id: str,
    rule_revision: str,
    source_sequence_index: Optional[int] = None,
) -> EligibilityProtocolRule:
    paragraph = builder.paragraph
    children = tuple(
        _freeze_rule(
            child,
            config,
            criterion_type,
            content_hash,
            f"{review_rule_id}.{index:02d}",
            rule_revision,
        )
        for index, child in enumerate(builder.children, start=1)
    )
    source_rule_label, numbering_status = _source_number_identity(
        paragraph,
        review_rule_id,
        source_sequence_index,
    )
    return EligibilityProtocolRule(
        project_id=config.project_id,
        criterion_uid=_criterion_uid(
            config.project_id,
            rule_revision,
            paragraph.source_locator,
            paragraph.text,
        ),
        rule_revision=rule_revision,
        review_rule_id=review_rule_id,
        source_rule_label=source_rule_label,
        numbering_status=numbering_status,
        criterion_type=criterion_type,
        text=paragraph.text,
        source_locator=paragraph.source_locator,
        source_entry=config.source_entry,
        source_version=config.source_version,
        content_hash=content_hash,
        word_num_id=paragraph.num_id,
        word_ilvl=paragraph.ilvl,
        numbering_format=paragraph.numbering_format,
        numbering_level_text=paragraph.numbering_level_text,
        children=children,
    )


def _source_number_identity(
    paragraph: ProtocolParagraph,
    review_rule_id: str,
    source_sequence_index: Optional[int],
) -> Tuple[Optional[str], str]:
    if (
        source_sequence_index is None
        or paragraph.ilvl != 0
        or paragraph.numbering_format != "decimal"
        or paragraph.numbering_level_text not in _CONFIRMED_NUMBERING_TEMPLATES
        or (
            paragraph.numbering_start is None
            and paragraph.numbering_start_override is None
        )
    ):
        return None, "source_number_unconfirmed"

    prefix = review_rule_id.split("-", 1)[0]
    sequence_start = (
        paragraph.numbering_start_override
        if paragraph.numbering_start_override is not None
        else paragraph.numbering_start
    )
    source_number = sequence_start + source_sequence_index - 1
    return f"{prefix}-{source_number:02d}", "source_sequence_verified"


def _criterion_uid(
    project_id: str,
    rule_revision: str,
    source_locator: str,
    text: str,
) -> str:
    digest = hashlib.sha256()
    for value in (
        "eligibility-criterion",
        _normalize_project_id(project_id),
        rule_revision,
        source_locator,
        _normalize_criterion_text(text),
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return f"eligcrit_{digest.hexdigest()[:24]}"


def _normalize_criterion_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def eligibility_criterion_text_hash(text: str) -> str:
    """Stable digest binding an AI criterion payload to parsed protocol text."""
    return hashlib.sha256(_normalize_criterion_text(text).encode("utf-8")).hexdigest()


def iter_rule_nodes(
    rules: Iterable[EligibilityProtocolRule],
) -> Iterable[EligibilityProtocolRule]:
    for rule in rules:
        yield rule
        yield from iter_rule_nodes(rule.children)
