"""DOCX source import/read routes; stored identity is not medical approval."""
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from packages.contracts.workbench_contracts.protocol_v3 import NonEmptyText, SourceRole
from app.protocol_workflow.agent1.docx_parse import parse_docx
from app.protocol_workflow.agent1.source_identity import SourceIdentityService

DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


class SourceMetadataCorrection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_role: SourceRole
    source_version: NonEmptyText
    jurisdiction: NonEmptyText


def create_source_router(service_factory: Callable[[], SourceIdentityService], *, route_class) -> APIRouter:
    router = APIRouter(prefix='/api/projects/{project_id}/protocol-workflow/sources',
                       tags=['方案资料'], route_class=route_class)

    @router.post('')
    def import_source(project_id: str, file: UploadFile = File(...),
                      logical_source_key: NonEmptyText = Form(...), source_role: SourceRole = Form(...),
                      source_version: NonEmptyText = Form('unidentified'), jurisdiction: NonEmptyText = Form('unspecified')):
        content = file.file.read()
        try:
            parsed = parse_docx(content)
        except (BadZipFile, ParseError, KeyError, ValueError) as exc:
            raise HTTPException(400, detail={
                'message': '这份文件暂时无法按 Word 方案读取，尚未加入资料。',
                'next_step': '请在 Word 中确认文件可以打开，并另存为 DOCX 后重选。',
            }) from exc
        try:
            result = service_factory().adopt(
                project_id=project_id, logical_source_key=logical_source_key, content=content,
                source_role=source_role, source_version=source_version, jurisdiction=jurisdiction,
                mime_type=DOCX_MIME, captured_at=datetime.now(timezone.utc),
            )
        except ValueError as exc:
            if str(exc).startswith('source_metadata_conflict:'):
                raise HTTPException(409, detail={
                    'message': '这份文件已保存，但本次选择的资料类别或版本信息不同。原记录已保留。',
                    'next_step': '请在已保存资料中更正类别与版本，无需重新上传。',
                }) from exc
            raise
        return {**asdict(result), 'parse': asdict(parsed), 'medical_admission': 'pending'}

    @router.get('')
    def list_sources(project_id: str):
        return {'sources': [asdict(record) for record in service_factory().list_current(project_id)]}

    @router.patch('/{source_artifact_id}/metadata')
    def correct_metadata(project_id: str, source_artifact_id: str, correction: SourceMetadataCorrection):
        try:
            result = service_factory().correct_metadata(
                project_id=project_id, source_artifact_id=source_artifact_id,
                **correction.model_dump(), changed_at=datetime.now(timezone.utc),
            )
        except LookupError as exc:
            raise HTTPException(404, detail={
                'message': '没有找到这份已保存的资料。', 'next_step': '请返回资料列表重新选择。',
            }) from exc
        except ValueError as exc:
            if str(exc) == 'source_revision_conflict':
                raise HTTPException(409, detail={
                    'message': '资料已有新版本，本次更正没有覆盖新版本。',
                    'next_step': '请刷新资料列表，在当前版本上更正。',
                }) from exc
            raise
        return asdict(result)

    def read(project_id: str, source_artifact_id: str) -> bytes:
        try:
            return service_factory().read_content(project_id, source_artifact_id)
        except LookupError as exc:
            raise HTTPException(404, detail={
                'message': '没有找到这份已保存的资料。', 'next_step': '请返回资料列表重新选择。',
            }) from exc

    @router.get('/{source_artifact_id}/parse')
    def parsed_source(project_id: str, source_artifact_id: str):
        return asdict(parse_docx(read(project_id, source_artifact_id)))

    @router.get('/{source_artifact_id}/content')
    def source_content(project_id: str, source_artifact_id: str):
        return Response(read(project_id, source_artifact_id), media_type=DOCX_MIME,
                        headers={'Content-Disposition': 'attachment; filename="source.docx"'})

    return router
