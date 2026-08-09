from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from packages.contracts.workbench_contracts import (
    AiTaskRunStatus,
    AiTaskSourceRef,
    ProtocolDocument,
    ProtocolSection,
)
from services.api.app.medical_writing import MedicalWritingRevisionService


class _CaptureRunner:
    def __init__(self) -> None:
        self.requests = []

    def submit_internal(self, project_id, request):
        self.requests.append((project_id, request))
        return SimpleNamespace(
            status=AiTaskRunStatus.COMPLETED,
            validation_errors=[],
            error_message="",
        )


class _DocumentService:
    def __init__(self, source_mode: str) -> None:
        self._source_mode = source_mode

    def source_mode(self, project_id: str) -> str:
        return self._source_mode

    def greenfield_state(self, project_id: str):
        return {"baseline_sha256": "a" * 64}


class _Repository:
    def __init__(self, source_mode: str) -> None:
        self.document_service = _DocumentService(source_mode)


def _protocol(project_id: str) -> ProtocolDocument:
    return ProtocolDocument(
        document_id=f"doc_{project_id}",
        project_id=project_id,
        protocol_id="CMS-D017-PH1",
        version="V0.1",
    )


def _section(protocol: ProtocolDocument) -> ProtocolSection:
    return ProtocolSection(
        section_id="section_design",
        document_id=protocol.document_id,
        heading="研究设计与安全性观察",
        section_number="4",
    )


def _company_source(project_id: str) -> AiTaskSourceRef:
    return AiTaskSourceRef(
        source_id="company:approved:001",
        source_type="company_protocol_reference_corpus",
        title="公司批准中文方案语料",
        locator="section:4|block:1",
        text_preview="本研究采用随机、双盲、安慰剂对照设计。",
        project_id=project_id,
        module="medical_writing",
    )


def _shared_source(project_id: str) -> AiTaskSourceRef:
    return AiTaskSourceRef(
        source_id="shared:phase1:001",
        source_type="shared_phase1_protocol_reference_corpus",
        title="公开I期竞品方案受控中文参考",
        locator="NCT00000000 protocol page 10",
        text_preview="安全性和耐受性将通过不良事件及临床实验室检查进行评价。",
        project_id=project_id,
        module="medical_writing",
    )


def _bind_reference_sources(service, project_id: str) -> None:
    service._company_corpus_sources = lambda *args, **kwargs: [
        _company_source(project_id)
    ]
    service._shared_corpus_sources = lambda *args, **kwargs: [
        _shared_source(project_id)
    ]


def test_greenfield_registered_source_route_includes_company_and_shared_corpus():
    project_id = "proj_phase1_greenfield"
    runner = _CaptureRunner()
    service = MedicalWritingRevisionService(
        _Repository("greenfield_project_decision"),
        runner,
    )
    _bind_reference_sources(service, project_id)
    protocol = _protocol(project_id)

    service._run_revision_ai(
        project_id,
        protocol,
        _section(protocol),
        "本研究为I期临床试验。",
        "优化为中国临床试验方案监管中文。",
        "regulatory_tone",
        "sections.design.blocks.0",
    )

    source_types = [
        source.source_type for source in runner.requests[0][1].allowed_sources
    ]
    assert source_types == [
        "greenfield_working_copy_selection",
        "company_protocol_reference_corpus",
        "shared_phase1_protocol_reference_corpus",
    ]


def test_real_registered_source_route_includes_company_and_shared_corpus():
    project_id = "proj_phase1_imported"
    runner = _CaptureRunner()
    service = MedicalWritingRevisionService(
        _Repository("original_protocol_docx"),
        runner,
        source_registry=object(),
        protocol_source_paths={project_id: Path("phase1-protocol.docx")},
    )
    _bind_reference_sources(service, project_id)
    service._register_revision_source = lambda **kwargs: SimpleNamespace(
        entry=SimpleNamespace(entry_id="src_entry_001"),
        spans=[
            SimpleNamespace(
                source_id="registered:source:001",
                source_type="protocol_docx",
                title="I期临床试验方案",
                locator="docx:paragraph:1",
                text_preview="本研究为I期临床试验。",
                project_id=project_id,
                module="medical_writing",
                entry_id="src_entry_001",
            )
        ],
    )
    protocol = _protocol(project_id)

    service._run_revision_ai(
        project_id,
        protocol,
        _section(protocol),
        "本研究为I期临床试验。",
        "优化为中国临床试验方案监管中文。",
        "regulatory_tone",
        "docx:paragraph:1",
    )

    source_types = [
        source.source_type for source in runner.requests[0][1].allowed_sources
    ]
    assert source_types == [
        "protocol_docx",
        "company_protocol_reference_corpus",
        "shared_phase1_protocol_reference_corpus",
    ]
