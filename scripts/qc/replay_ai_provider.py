from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from packages.contracts.workbench_contracts import (  # noqa: E402
    MedicalWritingPicosDefinition,
    MedicalWritingStudyFraming,
)


def build_completion(request_payload: Dict[str, Any]) -> Dict[str, Any]:
    messages = request_payload.get("messages") or []
    user_content = next(
        (
            message.get("content", "")
            for message in reversed(messages)
            if isinstance(message, dict) and message.get("role") == "user"
        ),
        "",
    )
    envelope = json.loads(user_content)
    sources = envelope.get("allowed_sources") or []
    if not sources:
        raise ValueError("QC replay requires at least one allowed source")
    source = sources[0]
    evidence_id = "qc_replay_protocol_id"
    framing = MedicalWritingStudyFraming(protocol_id="QC-REPLAY-001").model_dump(mode="json")
    picos = MedicalWritingPicosDefinition().model_dump(mode="json")
    missing_fields = [
        f"framing.{field}"
        for field in MedicalWritingStudyFraming().missing_required_fields()
        if field != "protocol_id"
    ] + [
        f"picos.{field}"
        for field in MedicalWritingPicosDefinition().missing_required_fields()
    ]
    output = {
        "task_id": envelope["task_id"],
        "task_type": envelope["task_type"],
        "provider": envelope["provider"],
        "model": envelope["model"],
        "prompt_version": envelope["prompt_version"],
        "input_source_ids": [item["source_id"] for item in sources],
        "forbidden_source_ids": envelope.get("forbidden_source_ids") or [],
        "findings": [],
        "evidence_spans": [
            {
                "span_id": evidence_id,
                "source_id": source["source_id"],
                "locator": source["locator"],
                "quote": source.get("text_preview", ""),
            }
        ],
        "uncertainties": [
            {
                "level": "data_gap",
                "description": "确定性浏览器回放仅验证前后端状态，不评价临床内容。",
            }
        ],
        "needs_medical_confirmation": True,
        "schema_version": envelope["schema_version"],
        "study_definition": {
            "framing": framing,
            "picos": picos,
            "synopsis_text": "确定性浏览器状态回放候选，非医学内容。",
            "missing_fields": missing_fields,
            "conflict_notes": [],
            "field_evidence_span_ids": {
                "framing.protocol_id": [evidence_id],
            },
        },
    }
    return {
        "id": "qc-replay-completion",
        "object": "chat.completion",
        "model": request_payload.get("model", "qc-replay-model"),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(output, ensure_ascii=False),
                },
                "finish_reason": "stop",
            }
        ],
    }


class ReplayHandler(BaseHTTPRequestHandler):
    server_version = "WorkbenchQcReplay/1.0"

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/v1/chat/completions":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request_payload = json.loads(self.rfile.read(length).decode("utf-8"))
            response = build_completion(request_payload)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._write_json(400, {"error": {"type": "qc_replay_error", "message": str(exc)}})
            return
        self._write_json(200, response)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _write_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), ReplayHandler).serve_forever()


if __name__ == "__main__":
    main()
