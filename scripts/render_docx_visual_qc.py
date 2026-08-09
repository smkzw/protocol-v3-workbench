from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

import fitz


DEFAULT_SOFFICE = Path(
    "/Users/smkzw/.cache/codex-runtimes/codex-primary-runtime/dependencies/"
    "bin/override/soffice"
)
CJK_FONT_PATTERN = re.compile(
    r"(?:Noto.*(?:CJK|SC)|SourceHan|Songti|STSong|PingFang|Heiti|Hiragino|ArialUnicode)",
    re.IGNORECASE,
)
CHINESE_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _font_directories() -> list[Path]:
    candidates = [
        Path.home() / "Library/Fonts",
        Path.home() / ".local/share/fonts",
        Path.home() / ".fonts",
        Path("/System/Library/Fonts"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/Library/Fonts"),
        Path("/usr/local/share/fonts"),
        Path("/usr/share/fonts"),
        DEFAULT_SOFFICE.parent.parent / "native/libreoffice-headless/libreoffice/"
        "LibreOfficeDev.app/Contents/Resources/fonts",
    ]
    return [path for path in candidates if path.exists()]


def build_fontconfig(font_directories: list[Path], cache_directory: Path) -> str:
    directories = "\n".join(f"  <dir>{escape(str(path))}</dir>" for path in font_directories)
    return f'''<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
{directories}
  <cachedir>{escape(str(cache_directory))}</cachedir>
  <alias binding="strong">
    <family>宋体</family>
    <prefer><family>Noto Serif SC</family><family>Songti SC</family><family>STSong</family><family>Arial Unicode MS</family></prefer>
  </alias>
  <alias binding="strong">
    <family>SimSun</family>
    <prefer><family>Noto Serif SC</family><family>Songti SC</family><family>STSong</family><family>Arial Unicode MS</family></prefer>
  </alias>
  <alias binding="strong">
    <family>黑体</family>
    <prefer><family>Noto Sans SC</family><family>Heiti SC</family><family>PingFang SC</family><family>Arial Unicode MS</family></prefer>
  </alias>
  <alias binding="strong">
    <family>SimHei</family>
    <prefer><family>Noto Sans SC</family><family>Heiti SC</family><family>PingFang SC</family><family>Arial Unicode MS</family></prefer>
  </alias>
  <alias binding="strong">
    <family>serif</family>
    <prefer><family>Noto Serif SC</family><family>Songti SC</family><family>STSong</family><family>Arial Unicode MS</family></prefer>
  </alias>
  <alias binding="strong">
    <family>sans-serif</family>
    <prefer><family>Noto Sans SC</family><family>PingFang SC</family><family>Heiti SC</family><family>Arial Unicode MS</family></prefer>
  </alias>
</fontconfig>
'''


def _ink_ratio(pixmap: fitz.Pixmap) -> float:
    if pixmap.width == 0 or pixmap.height == 0:
        return 0.0
    samples = pixmap.samples
    channels = pixmap.n
    colored = 0
    for offset in range(0, len(samples), channels):
        if min(samples[offset : offset + min(channels, 3)]) < 235:
            colored += 1
    return colored / (pixmap.width * pixmap.height)


def analyze_pdf(
    pdf_path: Path,
    *,
    expected_text: str = "",
    preview_directory: Path,
    max_preview_pages: int = 6,
) -> dict[str, object]:
    preview_directory.mkdir(parents=True, exist_ok=True)
    document = fitz.open(pdf_path)
    page_count = len(document)
    full_text = "\n".join(page.get_text("text") for page in document)
    fonts = sorted(
        {
            item[3]
            for page in document
            for item in page.get_fonts(full=True)
        }
    )
    chinese_spans: list[dict[str, object]] = []
    previews: list[str] = []
    for page_index, page in enumerate(document):
        if page_index < max_preview_pages:
            preview = preview_directory / f"page_{page_index + 1:03d}.png"
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(preview)
            previews.append(str(preview))
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = str(span.get("text") or "")
                    if not CHINESE_PATTERN.search(text):
                        continue
                    bbox = fitz.Rect(span["bbox"])
                    clip = bbox & page.rect
                    ratio = _ink_ratio(
                        page.get_pixmap(
                            matrix=fitz.Matrix(2, 2),
                            clip=clip,
                            alpha=False,
                        )
                    )
                    chinese_spans.append(
                        {
                            "page": page_index + 1,
                            "text": text[:80],
                            "font": span.get("font", ""),
                            "ink_ratio": round(ratio, 6),
                        }
                    )
    document.close()

    visible_spans = [span for span in chinese_spans if span["ink_ratio"] >= 0.01]
    checks = {
        "pdf_has_pages": bool(previews or full_text),
        "text_layer_contains_chinese": bool(CHINESE_PATTERN.search(full_text)),
        "expected_text_present": not expected_text or expected_text in full_text,
        "cjk_font_embedded": any(CJK_FONT_PATTERN.search(font) for font in fonts),
        "chinese_span_has_visible_pixels": bool(visible_spans),
    }
    return {
        "pdf_path": str(pdf_path),
        "page_count": page_count,
        "text_characters": len(full_text),
        "expected_text": expected_text,
        "embedded_fonts": fonts,
        "chinese_span_count": len(chinese_spans),
        "visible_chinese_span_count": len(visible_spans),
        "minimum_visible_ink_ratio": 0.01,
        "sample_chinese_spans": chinese_spans[:20],
        "preview_paths": previews,
        "checks": checks,
        "passed": all(checks.values()),
    }


def render_docx(
    docx_path: Path,
    output_directory: Path,
    *,
    soffice: Path,
    expected_text: str = "",
    max_preview_pages: int = 6,
) -> dict[str, object]:
    docx_path = docx_path.resolve()
    output_directory = output_directory.resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    if not docx_path.is_file():
        raise FileNotFoundError(docx_path)
    if not soffice.is_file():
        raise FileNotFoundError(soffice)

    with tempfile.TemporaryDirectory(prefix="mw-docx-qc-") as runtime:
        runtime_directory = Path(runtime)
        profile = runtime_directory / "profile"
        cache = runtime_directory / "font-cache"
        config_directory = runtime_directory / "fontconfig"
        home = runtime_directory / "home"
        for path in (profile, cache, config_directory, home):
            path.mkdir(parents=True, exist_ok=True)
        config = config_directory / "fonts.conf"
        font_directories = _font_directories()
        config.write_text(build_fontconfig(font_directories, cache), encoding="utf-8")

        env = os.environ.copy()
        env.update(
            {
                "FONTCONFIG_FILE": str(config),
                "FONTCONFIG_PATH": str(config_directory),
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / "xdg-config"),
                "XDG_CACHE_HOME": str(home / "xdg-cache"),
            }
        )
        Path(env["XDG_CONFIG_HOME"]).mkdir()
        Path(env["XDG_CACHE_HOME"]).mkdir()
        command = [
            str(soffice),
            f"-env:UserInstallation=file://{profile}",
            "--invisible",
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_directory),
            str(docx_path),
        ]
        process = subprocess.run(
            command,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    pdf_path = output_directory / f"{docx_path.stem}.pdf"
    report: dict[str, object] = {
        "input_docx": str(docx_path),
        "soffice": str(soffice),
        "font_directories": [str(path) for path in font_directories],
        "command": command,
        "returncode": process.returncode,
        "stdout": process.stdout,
        "stderr": process.stderr,
        "pdf_exists": pdf_path.is_file(),
    }
    if process.returncode == 0 and pdf_path.is_file():
        report.update(
            analyze_pdf(
                pdf_path,
                expected_text=expected_text,
                preview_directory=output_directory / "pages",
                max_preview_pages=max_preview_pages,
            )
        )
    else:
        report["passed"] = False
        report["checks"] = {"conversion_succeeded": False}
    report_path = output_directory / "visual_qc_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a DOCX with deterministic CJK font discovery and verify visible Chinese glyphs."
    )
    parser.add_argument("docx", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--expected-text", default="")
    parser.add_argument("--max-preview-pages", type=int, default=6)
    parser.add_argument(
        "--soffice",
        type=Path,
        default=Path(os.environ.get("SOFFICE_BIN", DEFAULT_SOFFICE)),
    )
    args = parser.parse_args()
    report = render_docx(
        args.docx,
        args.output_dir,
        soffice=args.soffice,
        expected_text=args.expected_text,
        max_preview_pages=max(1, args.max_preview_pages),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
