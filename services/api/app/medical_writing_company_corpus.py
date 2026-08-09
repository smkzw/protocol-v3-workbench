from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

from packages.contracts.workbench_contracts import MedicalWritingCorpusSnapshotDefinition

from .medical_writing_corpus_policy import (
    HARD_TARGET_DOMAINS,
    SPECIFIC_HARD_TARGET_DOMAINS,
    corpus_text_facet_match,
    governance_quality,
    infer_corpus_function,
    plan_corpus_facets,
    plan_not_applicable_module_filter,
    project_fact_slots,
    project_match_score,
    quality_flags,
    reuse_policy,
    row_domain_tags,
    row_text_domain_tags,
    section_fit_score,
    source_policy,
    target_domain_tags,
    text_quality,
)


ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets/medical_writing_corpus"
SNAPSHOT_PATH = ASSET_ROOT / "cms_cn_protocol_corpus_20260715_v1.jsonl"
MANIFEST_PATH = SNAPSHOT_PATH.with_suffix(".manifest.json")

_SEARCH_EQUIVALENCE_GROUPS: tuple[tuple[str, ...], ...] = (
    ("poc", "概念验证"),
    ("pom", "机制验证", "作用机制验证"),
    ("pd", "药效学"),
    ("pk", "药代动力学"),
    ("soa", "研究流程表", "schedule of activities"),
    ("hcg", "人绒毛膜促性腺激素"),
    ("fsh", "促卵泡激素"),
    ("ae", "不良事件"),
    ("sae", "严重不良事件"),
    ("aesi", "特别关注的不良事件", "特殊关注不良事件"),
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _search_features(value: str) -> set[str]:
    normalized = value.casefold()
    latin = set(re.findall(r"[a-z0-9][a-z0-9._-]{1,}", normalized))
    cjk_sequences = re.findall(r"[\u4e00-\u9fff]+", normalized)
    bigrams = {
        sequence[index : index + 2]
        for sequence in cjk_sequences
        for index in range(max(0, len(sequence) - 1))
    }
    trigrams = {
        sequence[index : index + 3]
        for sequence in cjk_sequences
        for index in range(max(0, len(sequence) - 2))
    }
    features = latin | bigrams | trigrams
    compact = re.sub(r"\s+", " ", normalized).strip()
    for group in _SEARCH_EQUIVALENCE_GROUPS:
        if any(term in compact for term in group):
            features.update(group)
    return features


def _query_anchor_groups(value: str) -> list[set[str]]:
    groups: list[set[str]] = []
    seen: set[tuple[str, ...]] = set()
    for token in re.findall(r"[a-z][a-z0-9._-]{1,}|[\u4e00-\u9fff]{2,}", value.casefold()):
        group = {token}
        for equivalents in _SEARCH_EQUIVALENCE_GROUPS:
            if token in equivalents:
                group.update(equivalents)
        key = tuple(sorted(group))
        if key not in seen:
            seen.add(key)
            groups.append(group)
    return groups


def _normalized_text_key(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


class MedicalWritingCompanyCorpusService:
    def __init__(
        self,
        snapshot_path: Path = SNAPSHOT_PATH,
        manifest_path: Path = MANIFEST_PATH,
    ):
        self.snapshot_path = Path(snapshot_path)
        self.manifest_path = Path(manifest_path)
        self._rows: list[dict[str, Any]] | None = None
        self._definition: MedicalWritingCorpusSnapshotDefinition | None = None

    def definition(self) -> MedicalWritingCorpusSnapshotDefinition:
        if self._definition is not None:
            return self._definition
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        observed_sha256 = _file_sha256(self.snapshot_path)
        if observed_sha256 != manifest.get("snapshot_sha256"):
            raise ValueError("company protocol corpus snapshot hash does not match its manifest")
        authority = (
            "公司中文方案语料快照：CMS-D017-PNH方案摘要v0.2为摘要类最高参照；"
            "D005 clean为次级摘要参照；公司全文方案补足完整章节；MY004摘要用于跨项目参考。"
        )
        self._definition = MedicalWritingCorpusSnapshotDefinition(
            snapshot_id=manifest["snapshot_id"],
            snapshot_version=manifest["snapshot_version"],
            snapshot_sha256=observed_sha256,
            schema_version=manifest["schema_version"],
            authority=authority,
            entry_count=manifest["entry_count"],
            base_library=manifest["base_library"],
            supplemental_sources=manifest["supplemental_sources"],
        )
        return self._definition

    def search(
        self,
        query: str,
        *,
        section_heading: str = "",
        section_number: str = "",
        template_node_id: str = "",
        interaction_types: Iterable[str] = (),
        corpus_function: str = "",
        project_indication: str = "",
        project_phase: str = "",
        limit: int = 5,
        include_table_rows: bool | None = None,
        plan_design_drivers: list[dict[str, Any]] | None = None,
        plan_not_applicable_modules: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        if limit < 1 or limit > 20:
            raise ValueError("company protocol corpus search limit must be between 1 and 20")
        self.definition()
        plan_facets = plan_corpus_facets(plan_design_drivers or [])
        not_applicable_modules = plan_not_applicable_modules or []
        resolved_function = infer_corpus_function(
            corpus_function,
            section_number=section_number,
            template_node_id=template_node_id,
            section_heading=section_heading,
            interaction_types=interaction_types,
        )
        target_tags = target_domain_tags(
            section_number=section_number,
            template_node_id=template_node_id,
            section_heading=f"{section_heading} {query}",
        )
        if include_table_rows is None:
            include_table_rows = (
                resolved_function in {"synopsis", "table_soa"}
                or bool(target_tags & {"analysis_set_definition", "estimand_definition"})
            )
        query_features = _search_features(query)
        query_anchor_groups = _query_anchor_groups(query)
        query_latin_tokens = set(
            re.findall(r"[a-z][a-z0-9._-]{1,}", query.casefold())
        )
        section_features = _search_features(
            f"{section_number} {template_node_id} {section_heading}"
        )
        if not query_features:
            return []
        scored: list[tuple[float, float, float, dict[str, Any], dict[str, Any]]] = []
        for row in self._candidate_rows(target_tags):
            if not include_table_rows and str(row.get("block_type") or "") in {
                "table",
                "table_row",
            }:
                continue
            text = str(row.get("text") or "")
            text_features = _search_features(text)
            text_latin_tokens = set(
                re.findall(r"[a-z][a-z0-9._-]{1,}", text.casefold())
            )
            latin_token_coverage = (
                len(query_latin_tokens & (text_latin_tokens | text_features)) / len(query_latin_tokens)
                if query_latin_tokens
                else 0.0
            )
            compact_candidate = re.sub(r"\s+", " ", text.casefold()).strip()
            anchor_term_coverage = (
                sum(
                    any(term in compact_candidate or term in text_features for term in group)
                    for group in query_anchor_groups
                )
                / len(query_anchor_groups)
                if query_anchor_groups
                else 0.0
            )
            query_overlap = len(query_features & text_features)
            if not query_overlap:
                continue
            lexical_relevance = query_overlap / math.sqrt(
                max(1, len(query_features) * len(text_features))
            )
            query_feature_recall = query_overlap / max(1, len(query_features))
            metadata_features = _search_features(
                f"{row.get('section', '')} {' '.join(row.get('categories') or [])}"
            )
            section_relevance = 0.0
            if section_features:
                section_overlap = len(section_features & (text_features | metadata_features))
                section_relevance = section_overlap / math.sqrt(
                    max(1, len(section_features) * len(text_features | metadata_features))
                )
            compact_query = re.sub(r"\s+", "", query.casefold())
            compact_text = re.sub(r"\s+", "", text.casefold())
            if len(compact_query) >= 4 and compact_query in compact_text:
                lexical_relevance = min(1.0, lexical_relevance + 0.25)

            policy = source_policy(str(row.get("source_file") or ""))
            candidate_tags = row_domain_tags(row)
            candidate_text_tags = row_text_domain_tags(row)
            m11_fit = section_fit_score(target_tags, candidate_tags)
            hard_target_tags = target_tags & HARD_TARGET_DOMAINS
            specific_hard_target_tags = hard_target_tags & SPECIFIC_HARD_TARGET_DOMAINS
            mandatory_target_tags = specific_hard_target_tags or hard_target_tags
            if mandatory_target_tags and not mandatory_target_tags.issubset(candidate_text_tags):
                continue
            project_match, project_match_reason = project_match_score(
                policy,
                project_indication,
                project_phase,
            )
            if (
                "dosing_instruction" in hard_target_tags
                and project_indication.strip()
                and project_match < 1.0
            ):
                continue
            fact_slots = project_fact_slots(text)
            if (
                project_indication.strip()
                and project_match == 0.0
                and set(fact_slots)
                & {
                    "dose_or_concentration",
                    "visit_or_timepoint",
                    "threshold",
                    "sample_size",
                    "endpoint_or_scale",
                }
            ):
                continue
            row_reuse_policy = reuse_policy(
                row,
                policy,
                project_match=project_match,
                fact_slots=fact_slots,
            )
            quality, row_quality_flags = text_quality(row)
            if quality == 0.0:
                continue
            # Plan-driven hard filter: exclude entries describing modules
            # the plan has marked not_applicable.
            if not_applicable_modules and plan_not_applicable_module_filter(
                text, not_applicable_modules
            ):
                continue
            # Plan-driven facet scoring: penalize or boost based on
            # confirmed design drivers (modality/route/interim/comparator).
            facet_adjustment, facet_reasons = corpus_text_facet_match(
                text,
                str(row.get("source_file") or ""),
                policy,
                plan_facets,
            )
            if (
                row.get("reuse_level") == "disease_specific_reference"
                and project_indication.strip()
                and project_match == 0.0
            ):
                continue
            function_authority = policy.authority(resolved_function)
            governance = governance_quality(policy)
            block_fit = 1.0
            if resolved_function == "table_soa":
                block_fit = 1.0 if row.get("block_type") in {"table", "table_row"} else 0.65
            elif row.get("block_type") in {"table", "table_row"}:
                block_fit = 0.72
            anchor_coverage_weight = 0.12 if len(query_anchor_groups) >= 2 else 0.0
            latin_coverage_weight = 0.04 if query_latin_tokens else 0.0
            query_recall_weight = 0.10
            lexical_weight = 0.43 - anchor_coverage_weight - latin_coverage_weight - query_recall_weight
            total_score = (
                lexical_weight * lexical_relevance
                + query_recall_weight * query_feature_recall
                + anchor_coverage_weight * anchor_term_coverage
                + latin_coverage_weight * latin_token_coverage
                + 0.08 * section_relevance
                + 0.18 * m11_fit
                + 0.11 * function_authority
                + 0.10 * project_match
                + 0.06 * quality
                + 0.02 * governance
                + 0.02 * block_fit
            )
            if policy.superseded:
                total_score -= 0.18
            # Apply plan-driven facet adjustment after base score computation.
            total_score += facet_adjustment
            if resolved_function == "table_soa" and re.match(
                r"^(?:研究|试验)?(?:阶段|周数|日)|^访视|^时间窗",
                text,
            ):
                total_score += 0.18
            if "study_end_definition" in mandatory_target_tags and re.search(
                r"血样|采样|样本采集",
                text,
            ):
                total_score -= 0.12
            if project_indication.strip() and project_match == 0.0:
                total_score -= 0.12
            if row_reuse_policy == "reference_only":
                total_score -= 0.03
            if "bare_heading" in row_quality_flags:
                total_score -= 0.08
            selection = {
                "corpus_function": resolved_function,
                "m11_target_tags": sorted(target_tags),
                "candidate_domain_tags": sorted(candidate_tags),
                "candidate_text_domain_tags": sorted(candidate_text_tags),
                "project_match": round(project_match, 4),
                "project_match_reason": project_match_reason,
                "function_authority": round(function_authority, 4),
                "governance_status": policy.governance_status,
                "reuse_policy": row_reuse_policy,
                "project_fact_slots": fact_slots,
                "quality_flags": sorted(set(row_quality_flags + quality_flags(text))),
                "score_components": {
                    "lexical_relevance": round(lexical_relevance, 6),
                    "query_feature_recall": round(query_feature_recall, 6),
                    "anchor_term_coverage": round(anchor_term_coverage, 6),
                    "latin_token_coverage": round(latin_token_coverage, 6),
                    "section_relevance": round(section_relevance, 6),
                    "m11_section_fit": round(m11_fit, 6),
                    "function_authority": round(function_authority, 6),
                    "project_match": round(project_match, 6),
                    "text_quality": round(quality, 6),
                    "governance_quality": round(governance, 6),
                    "block_fit": round(block_fit, 6),
                },
            }
            if row.get("source_entry_ids"):
                selection["reconstruction"] = {
                    "type": "adjacent_same_source_window",
                    "source_entry_ids": list(row["source_entry_ids"]),
                }
            if facet_reasons:
                selection["plan_facet_reasons"] = facet_reasons
            scored.append((total_score, m11_fit, function_authority, row, selection))
        scored.sort(
            key=lambda item: (
                -item[0],
                -item[1],
                -item[2],
                _normalized_text_key(str(item[3].get("text") or "")),
                str(item[3].get("entry_id") or ""),
            )
        )
        result: list[dict[str, Any]] = []
        per_source: dict[str, int] = {}
        seen_text_keys: set[str] = set()
        seen_canonical_ids: set[str] = set()
        for relevance, _, _, row, selection in scored:
            source_file = str(row.get("source_file") or "")
            text_key = _normalized_text_key(str(row.get("text") or ""))
            canonical_id = str(row.get("canonical_entry_id") or row.get("entry_id") or "")
            if (
                text_key in seen_text_keys
                or canonical_id in seen_canonical_ids
                or per_source.get(source_file, 0) >= 2
            ):
                continue
            result.append(
                {
                    **row,
                    "retrieval_score": round(relevance, 6),
                    "selection": selection,
                    "snapshot_id": self.definition().snapshot_id,
                    "snapshot_version": self.definition().snapshot_version,
                    "snapshot_sha256": self.definition().snapshot_sha256,
                }
            )
            seen_text_keys.add(text_key)
            seen_canonical_ids.add(canonical_id)
            per_source[source_file] = per_source.get(source_file, 0) + 1
            if len(result) >= limit:
                break
        return result

    def _candidate_rows(self, target_tags: set[str]) -> Iterable[dict[str, Any]]:
        rows = self._load_rows()
        yield from rows
        if "estimand_definition" in target_tags:
            for left, right in zip(rows, rows[1:]):
                if (
                    left.get("source_file") != right.get("source_file")
                    or left.get("block_type") != "table"
                    or right.get("block_type") != "table"
                ):
                    continue
                yield self._semantic_window([left, right])
        if "contraception_complete_clause" in target_tags:
            for index, first in enumerate(rows):
                if not re.search(r"避孕|生育能力|生育潜能", str(first.get("text") or "")):
                    continue
                window = [first]
                for following in rows[index + 1 : index + 6]:
                    if (
                        following.get("source_file") != first.get("source_file")
                        or following.get("section") != first.get("section")
                        or following.get("block_type") != first.get("block_type")
                    ):
                        break
                    window.append(following)
                if len(window) > 1:
                    yield self._semantic_window(window)
        if "drug_accountability_lifecycle" in target_tags:
            for index, first in enumerate(rows):
                if not re.search(
                    r"IMP|试验药物|研究药物|试验用药品",
                    str(first.get("text") or ""),
                    re.I,
                ):
                    continue
                window = [first]
                for following in rows[index + 1 : index + 4]:
                    if (
                        following.get("source_file") != first.get("source_file")
                        or following.get("block_type") != first.get("block_type")
                    ):
                        break
                    window.append(following)
                if len(window) > 1:
                    yield self._semantic_window(window)

    @staticmethod
    def _semantic_window(rows: list[dict[str, Any]]) -> dict[str, Any]:
        source_entry_ids = [str(row.get("entry_id") or "") for row in rows]
        combined_text = "\n".join(
            str(row.get("text") or "").strip() for row in rows if str(row.get("text") or "").strip()
        )
        window_id = ":".join(source_entry_ids)
        return {
            **rows[0],
            "entry_id": f"semantic_window:{window_id}",
            "canonical_entry_id": f"semantic_window:{window_id}",
            "text": combined_text,
            "text_hash": hashlib.sha256(combined_text.encode("utf-8")).hexdigest()[:16],
            "source_entry_ids": source_entry_ids,
            "block_type": rows[0].get("block_type") or "paragraph",
        }

    def _load_rows(self) -> list[dict[str, Any]]:
        if self._rows is None:
            rows: list[dict[str, Any]] = []
            with self.snapshot_path.open(encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        rows.append(json.loads(line))
            if len(rows) != self.definition().entry_count:
                raise ValueError("company protocol corpus entry count does not match its manifest")
            self._rows = rows
        return self._rows
