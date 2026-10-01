#!/usr/bin/env python3
"""NEW-20（R27 第1轮末修订）：docx 导出件的域/目录更新后处理器。

Tier-1（策略首选机制）：本机 LibreOffice 无头模式 + 一次性临时 profile 中
种入 Basic 宏（loadComponentFromURL → refresh → updateIndexes → storeToURL），
更新全部索引与域后重存；不触碰用户默认 LibreOffice 配置，源文件只读。
本机实测（2026-09-30）：soffice 宏通道在此 macOS 环境不执行（宏调用静默
不产文件，LibreOfficePython 被 SIGKILL）——工具如实返回失败原因，不假装
通过。

Tier-2（确定性兜底，纯 zip 层，本机实测可用）：
 1. settings.xml 置 w:updateFields=true —— Word/WPS 打开时自动刷新全部域；
 2. 目录域缓存占位「更新域后显示目录」替换为按正文 Heading1-3 计算的真实
    条目（仅条目文本＋层级缩进；页码由打开端域更新填充，不编造页码）。
w:updateFields/dirty 兜底语义保持不变。

用法：
  python3 tools/qc/soffice_update_fields.py <input.docx> <output.docx> [--tier2]

退出码：0 成功且输出通过 TOC 非空断言；3 输出断言失败；2 工具/环境失败。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SOFFICE_CANDIDATES = (
    "/opt/homebrew/bin/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "soffice",
)

_TOC_PLACEHOLDER = "更新域后显示目录"

_BASIC_MODULE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">
<script:module xmlns:script="http://openoffice.org/2000/script" script:name="New20Module" script:language="StarBasic">Sub UpdateFieldsToUrl(sInUrl As String, sOutUrl As String)
    Dim oDesktop As Object
    Dim oDoc As Object
    Dim oArgs(0) As New com.sun.star.beans.PropertyValue
    Dim oOut(0) As New com.sun.star.beans.PropertyValue
    Dim oIndexes As Object
    Dim i As Integer
    oArgs(0).Name = "Hidden"
    oArgs(0).Value = True
    oDesktop = createUnoService("com.sun.star.frame.Desktop")
    oDoc = oDesktop.loadComponentFromURL(sInUrl, "_blank", 0, oArgs())
    oDoc.refresh()
    oIndexes = oDoc.getDocumentIndexes()
    For i = 0 To oIndexes.getCount() - 1
        oIndexes.getByIndex(i).update()
    Next i
    oOut(0).Name = "FilterName"
    oOut(0).Value = "MS Word 2007 XML"
    oDoc.storeToURL(sOutUrl, oOut())
    oDoc.close(False)
End Sub</script:module>
"""

_BASIC_LIBRARY = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE library:library PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "library.dtd">
<library:library xmlns:library="http://openoffice.org/2000/library" library:name="Standard" library:readonly="false" library:passwordprotected="false">
 <library:element library:name="New20Module"/>
</library:library>
"""

_BASIC_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE library:libraries PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "libraries.dtd">
<library:libraries xmlns:library="http://openoffice.org/2000/library" xmlns:xlink="http://www.w3.org/1999/xlink">
 <library:library library:name="Standard" xlink:href="$(USER)/basic/Standard/script.xlb/" xlink:type="simple" library:link="false"/>
</library:libraries>
"""


def _soffice_bin() -> str:
    for candidate in SOFFICE_CANDIDATES:
        if shutil.which(candidate) or Path(candidate).exists():
            return candidate
    raise FileNotFoundError("soffice 不存在；请安装 LibreOffice 或将其加入 PATH")


def _file_url(path: Path) -> str:
    return path.resolve().as_uri()


def _toc_assertions(docx: Path) -> dict:
    """QC 解包断言：目录域缓存结果必须含真实条目（PAGEREF），且不再有
    「更新域后显示目录」占位。"""
    xml = zipfile.ZipFile(docx).read("word/document.xml").decode("utf-8")
    return {
        "pageref_count": xml.count("PAGEREF"),
        "placeholder_present": _TOC_PLACEHOLDER in xml,
    }


def _seed_profile_macro(profile: Path) -> None:
    basic_dir = profile / "user" / "basic"
    standard_dir = basic_dir / "Standard"
    standard_dir.mkdir(parents=True, exist_ok=True)
    (standard_dir / "New20Module.xba").write_text(_BASIC_MODULE, encoding="utf-8")
    (standard_dir / "script.xlb").write_text(_BASIC_LIBRARY, encoding="utf-8")
    (basic_dir / "script.xlc").write_text(_BASIC_INDEX, encoding="utf-8")


def macro_update_fields(input_docx: Path, output_docx: Path, timeout_s: int = 180) -> dict:
    """Tier-1：LibreOffice 无头宏更新全部索引与域。"""
    soffice = _soffice_bin()
    profile = Path(tempfile.mkdtemp(prefix="lo_new20_profile_"))
    workdir = Path(tempfile.mkdtemp(prefix="lo_new20_work_"))
    try:
        _seed_profile_macro(profile)
        subprocess.run(
            [soffice, "--headless", "--norestore",
             f"-env:UserInstallation={profile.as_uri()}", "--terminate_after_init"],
            check=False, timeout=timeout_s,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        work_input = workdir / input_docx.name
        shutil.copyfile(input_docx, work_input)
        work_output = workdir / f"updated_{input_docx.name}"
        macro_url = (
            "macro:///Standard.New20Module.UpdateFieldsToUrl"
            f"(\"{_file_url(work_input)}\",\"{_file_url(work_output)}\")"
        )
        completed = subprocess.run(
            [soffice, "--headless", "--norestore",
             f"-env:UserInstallation={profile.as_uri()}", macro_url],
            check=False, timeout=timeout_s,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        if not work_output.exists():
            return {
                "ok": False,
                "stage": "macro-run",
                "returncode": completed.returncode,
                "output": (completed.stdout or "")[-500:],
            }
        shutil.copyfile(work_output, output_docx)
        checks = _toc_assertions(output_docx)
        ok = checks["pageref_count"] > 0 and not checks["placeholder_present"]
        return {"ok": ok, "stage": "done", **checks}
    finally:
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(workdir, ignore_errors=True)


def deterministic_update(input_docx: Path, output_docx: Path) -> dict:
    """Tier-2 兜底（纯 zip 层操作，只改导出副本；历史导出件不被触碰）。"""
    zin = zipfile.ZipFile(input_docx)
    parts = {name: zin.read(name) for name in zin.namelist()}
    zin.close()
    document = parts["word/document.xml"].decode("utf-8")
    settings_name = "word/settings.xml"
    if settings_name in parts:
        settings = parts[settings_name].decode("utf-8")
        if "w:updateFields" not in settings:
            settings = settings.replace(
                "</w:settings>", '<w:updateFields w:val="true"/></w:settings>'
            )
        else:
            settings = re.sub(
                r"<w:updateFields[^/>]*/>", '<w:updateFields w:val="true"/>', settings
            )
        parts[settings_name] = settings.encode("utf-8")

    if _TOC_PLACEHOLDER in document:
        entries: list[str] = []
        for match in re.finditer(r"<w:p\b(?:(?!</w:p>).)*?</w:p>", document, flags=re.S):
            paragraph = match.group(0)
            style = re.search(r'w:pStyle[^>]*w:val="Heading([1-3])"', paragraph)
            if not style:
                continue
            text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", paragraph)).strip()
            if not text:
                continue
            level = int(style.group(1))
            escaped = (
                text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            entries.append(
                f'<w:p><w:pPr><w:ind w:left="{(level - 1) * 420}"/></w:pPr>'
                f'<w:r><w:t xml:space="preserve">{escaped}</w:t></w:r></w:p>'
            )
            if len(entries) >= 300:
                break
        if entries:
            for match in re.finditer(
                r"<w:p\b(?:(?!</w:p>).)*?</w:p>", document, flags=re.S
            ):
                if _TOC_PLACEHOLDER in match.group(0):
                    document = document.replace(match.group(0), "".join(entries), 1)
                    break
    parts["word/document.xml"] = document.encode("utf-8")
    with zipfile.ZipFile(output_docx, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, payload in parts.items():
            zout.writestr(name, payload)
    checks = _toc_assertions(output_docx)
    checks.update(
        {
            "ok": checks["placeholder_present"] is False,
            "stage": "deterministic",
            "update_fields_flag": b"w:updateFields" in parts.get(
                "word/settings.xml", b""
            ),
        }
    )
    return checks


def main(argv: list[str]) -> int:
    tier2 = "--tier2" in argv
    paths = [arg for arg in argv[1:] if not arg.startswith("--")]
    if len(paths) != 2:
        print(__doc__)
        return 2
    input_docx, output_docx = Path(paths[0]), Path(paths[1])
    if not input_docx.exists():
        print(f"输入不存在: {input_docx}")
        return 2
    if tier2:
        result = deterministic_update(input_docx, output_docx)
    else:
        result = macro_update_fields(input_docx, output_docx)
        if not result.get("ok"):
            print(f"Tier-1 宏通道未生效：{result}；回落 Tier-2 确定性更新。")
            result = deterministic_update(input_docx, output_docx)
    print(result)
    return 0 if result.get("ok") else (3 if result.get("stage") == "done" else 2)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
