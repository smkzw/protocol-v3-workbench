"""HTTP boundary for the one-way authoring-journey manuscript bridge."""
from __future__ import annotations

import hashlib
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from packages.contracts.workbench_contracts.protocol_v3 import StableId, Sha256
from app.protocol_workflow.application.authoring_bridge import authoring_bridge_study_id
from app.protocol_workflow.canonical.hashing import canonical_json


class AuthoringHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor_id: StableId


class FullDraftCandidateAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: StableId
    actor_id: StableId
    expected_revision: int = Field(ge=0, strict=True)
    expected_document_sha256: Sha256 | None = None
    accepted_semantic_node_ids: list[StableId] = Field(default_factory=list)


class SourcePolicyConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: StableId
    actor_id: StableId
    routine_scope: list[str] = Field(min_length=1, max_length=12)
    excluded_scope: list[str] = Field(default_factory=list, max_length=12)


def create_authoring_bridge_router(
    bridge: Any,
    journey_provider: Callable[[str], Any],
    artifact_provider: Callable[[str, str], tuple[dict[str, Any], str]],
    *,
    route_class: type,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/projects/{project_id}/protocol-workflow/authoring-handoff",
        tags=["研究方案写作"],
        route_class=route_class,
    )

    def checked(fn):
        try:
            return fn()
        except HTTPException:
            raise
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(
                404,
                detail={"message": "没有找到本项目已确认的研究设计或候选初稿。"},
            ) from exc
        except ValueError as exc:
            code = str(exc)
            if code in {
                "authoring_journey_study_definition_missing",
                "manuscript_study_missing",
            }:
                raise HTTPException(
                    404, detail={"code": code, "message": "本项目尚无可沿用的已确认研究设计。"}
                ) from exc
            if code in {
                "manuscript_document_revision_changed",
                "manuscript_candidate_intent_changed",
                "full_draft_study_binding_changed",
            }:
                raise HTTPException(
                    409,
                    detail={
                        "code": code,
                        "message": "当前研究或文档已有更新，本次候选没有覆盖最新工作稿。",
                        "next_step": "读取最新工作稿后重新核对要采用的章节。",
                    },
                ) from exc
            if code == "source_changed":
                raise HTTPException(
                    409,
                    detail={"code": code, "message": "已确认研究设计已有新版本，请先核对本次沿用范围。"},
                ) from exc
            raise HTTPException(
                422,
                detail={
                    "code": code,
                    "message": "候选初稿与当前研究或模板不匹配，现有工作稿未被修改。",
                },
            ) from exc
        except Exception as exc:
            raise HTTPException(
                500,
                detail={
                    "code": "authoring_handoff_unknown_outcome",
                    "message": "接线状态暂时无法确认，现有研究内容和工作稿均已保留。",
                    "next_step": "请先刷新核对当前工作稿，不要重复确认研究决定。",
                },
            ) from exc

    @router.post("")
    def ensure_authoring_handoff(project_id: str, body: AuthoringHandoffRequest):
        return checked(
            lambda: bridge.ensure_study(
                project_id, journey_provider(project_id), actor_id=body.actor_id
            )
        )

    @router.post("/full-draft-candidates/{job_id}/accept")
    def accept_full_draft_candidate(
        project_id: str, job_id: str, body: FullDraftCandidateAcceptRequest
    ):
        def execute():
            artifact, artifact_sha256 = artifact_provider(project_id, job_id)
            return bridge.accept_full_draft(
                project_id,
                journey_provider(project_id),
                artifact,
                artifact_sha256,
                actor_id=body.actor_id,
                operation_id=body.operation_id,
                expected_revision=body.expected_revision,
                expected_document_sha256=body.expected_document_sha256,
                accepted_semantic_node_ids=body.accepted_semantic_node_ids,
            )

        return checked(execute)

    @router.post("/full-draft-candidates/{job_id}/recover")
    def recover_full_draft_candidate(
        project_id: str, job_id: str, body: FullDraftCandidateAcceptRequest
    ):
        # The same immutable candidate + operation intent is the recovery key.
        # The application service returns the recorded receipt without a write.
        return accept_full_draft_candidate(project_id, job_id, body)

    def source_policy_material(project_id: str, job_id: str):
        artifact, _ = artifact_provider(project_id, job_id)
        sources = [
            item for item in (artifact.get("source_manifest") or {}).get("sources") or []
            if item.get("role") == "company_sop_or_protocol_reference"
        ]
        if not sources:
            raise HTTPException(404, detail={
                "code": "source_policy_sources_missing",
                "message": "本次候选没有使用需项目级确认的公司SOP或方案参考。",
            })
        policy_source_sha256 = hashlib.sha256(canonical_json([
            {
                "source_id": item.get("source_id"),
                "source_version": item.get("source_version"),
                "content_sha256": item.get("content_sha256"),
                "locator": item.get("locator"),
            }
            for item in sorted(sources, key=lambda value: (
                str(value.get("source_id") or ""),
                str(value.get("content_sha256") or ""),
            ))
        ]).encode()).hexdigest()
        return policy_source_sha256, sources

    @router.get("/full-draft-candidates/{job_id}/source-policy")
    def read_source_policy(project_id: str, job_id: str):
        def execute():
            manifest_sha, sources = source_policy_material(project_id, job_id)
            return {
                **bridge.documents.source_policy_status(
                    project_id, authoring_bridge_study_id(project_id), manifest_sha
                ),
                "source_manifest_sha256": manifest_sha,
                "sources": sources,
            }
        return checked(execute)

    @router.post("/full-draft-candidates/{job_id}/source-policy")
    def confirm_source_policy(
        project_id: str, job_id: str, body: SourcePolicyConfirmRequest
    ):
        def execute():
            manifest_sha, sources = source_policy_material(project_id, job_id)
            return bridge.documents.confirm_source_policy(
                project_id,
                authoring_bridge_study_id(project_id),
                {
                    **body.model_dump(mode="json"),
                    "source_manifest_sha256": manifest_sha,
                    "source_ids": [item["source_id"] for item in sources],
                },
            )
        return checked(execute)

    return router
