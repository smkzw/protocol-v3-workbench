from __future__ import annotations

from email.message import Message
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from deploy.medical_writing_local.verify_release import read_json
from deploy.medical_writing_local.build_release_bundle import (
    commercial_word_engine_dependency_report,
    should_exclude_archive_path,
)


class _Response(BytesIO):
    def __init__(self, payload: bytes, status: int, content_type: str):
        super().__init__(payload)
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class MedicalWritingReleaseVerifierTests(unittest.TestCase):
    def _commercial_policy_fixture(
        self,
        *,
        python_source: str,
        frontend_dependencies: dict[str, str] | None = None,
    ) -> TemporaryDirectory:
        temporary = TemporaryDirectory()
        root = Path(temporary.name)
        backend = root / "services" / "api" / "app"
        backend.mkdir(parents=True)
        (backend / "exporter.py").write_text(python_source, encoding="utf-8")
        frontend = root / "frontend"
        frontend.mkdir()
        (frontend / "package.json").write_text(
            json.dumps(
                {
                    "dependencies": frontend_dependencies or {},
                    "devDependencies": {},
                }
            ),
            encoding="utf-8",
        )
        return temporary

    def test_commercial_word_engine_policy_accepts_open_source_toolchain(self):
        temporary = self._commercial_policy_fixture(
            python_source="from docx import Document\n"
        )
        self.addCleanup(temporary.cleanup)

        report = commercial_word_engine_dependency_report(Path(temporary.name))

        self.assertEqual("pass", report["status"])
        self.assertEqual([], report["findings"])
        self.assertEqual(
            "MIT",
            report["approved_toolchain"]["structural_validation_license"],
        )

    def test_commercial_word_engine_policy_rejects_backend_import(self):
        temporary = self._commercial_policy_fixture(
            python_source="import aspose.words\n"
        )
        self.addCleanup(temporary.cleanup)

        report = commercial_word_engine_dependency_report(Path(temporary.name))

        self.assertEqual("fail", report["status"])
        self.assertEqual("Aspose", report["findings"][0]["engine"])
        self.assertEqual(
            "backend_python_import", report["findings"][0]["surface"]
        )

    def test_commercial_word_engine_policy_rejects_frontend_dependency(self):
        temporary = self._commercial_policy_fixture(
            python_source="from docx import Document\n",
            frontend_dependencies={"@syncfusion/ej2-documenteditor": "1.0.0"},
        )
        self.addCleanup(temporary.cleanup)

        report = commercial_word_engine_dependency_report(Path(temporary.name))

        self.assertEqual("fail", report["status"])
        self.assertEqual("Syncfusion", report["findings"][0]["engine"])
        self.assertEqual(
            "frontend_dependencies", report["findings"][0]["surface"]
        )

    def test_release_archive_excludes_validator_build_intermediates(self):
        self.assertTrue(
            should_exclude_archive_path(
                Path("tools/openxml_docx_validator/obj/project.assets.json")
            )
        )
        self.assertTrue(
            should_exclude_archive_path(
                Path(
                    "tools/openxml_docx_validator/bin/Release/net8.0/"
                    "openxml-docx-validator"
                )
            )
        )
        self.assertFalse(
            should_exclude_archive_path(
                Path(
                    "tools/openxml_docx_validator/bin/osx-arm64/"
                    "openxml-docx-validator"
                )
            )
        )

    def test_read_json_accepts_json_response(self):
        response = _Response(b'{"ready": true}', 200, "application/json")
        with patch(
            "deploy.medical_writing_local.verify_release.urlopen",
            return_value=response,
        ):
            status, payload = read_json("http://127.0.0.1/test")
        self.assertEqual(200, status)
        self.assertEqual({"ready": True}, payload)

    def test_read_json_reports_non_json_response_without_crashing(self):
        response = _Response(b"<html>proxy failure</html>", 502, "text/html")
        with patch(
            "deploy.medical_writing_local.verify_release.urlopen",
            return_value=response,
        ):
            status, payload = read_json("http://127.0.0.1/test")
        self.assertEqual(502, status)
        self.assertEqual("response_is_not_json", payload["_read_error"])
        self.assertEqual("text/html", payload["_content_type"])

    def test_read_json_reports_non_json_http_error_without_crashing(self):
        headers = Message()
        headers["Content-Type"] = "text/html"
        error = HTTPError(
            "http://127.0.0.1/test",
            502,
            "Bad Gateway",
            headers,
            BytesIO(b"<html>bad gateway</html>"),
        )
        with patch(
            "deploy.medical_writing_local.verify_release.urlopen",
            side_effect=error,
        ):
            status, payload = read_json("http://127.0.0.1/test")
        self.assertEqual(502, status)
        self.assertEqual(
            "http_error_response_is_not_json", payload["_read_error"]
        )

    def test_read_json_reports_unreachable_endpoint_without_crashing(self):
        with patch(
            "deploy.medical_writing_local.verify_release.urlopen",
            side_effect=URLError("connection refused"),
        ):
            status, payload = read_json("http://127.0.0.1/test")
        self.assertEqual(0, status)
        self.assertEqual("endpoint_unreachable", payload["_read_error"])


if __name__ == "__main__":
    unittest.main()
