from __future__ import annotations

import hashlib
import json

from packages.contracts.workbench_contracts import MedicalWritingStyleProfileDefinition


STYLE_PROFILE_ID = "cms_cn_clinical_protocol"
STYLE_PROFILE_VERSION = "cms_cn_clinical_protocol_2026_07_v1"

_SOURCE_DOCUMENTS = [
    {
        "title": "CMS-D017-PNH-方案摘要_v0.2.docx",
        "sha256": "dcd60942b1a77b2b109583923d0126ae86481a4a12d44c873e26f010463ba4da",
        "authority_role": "P0：方案摘要、中文表达、首页、概要表格、研究流程表及附注的最高参照",
    },
    {
        "title": "CMS-D005-减重II期临床试验方案概要-V0.3-KZYY0525-clean-DIP0526-KZYY0526 (2).docx",
        "sha256": "6d2fa343bea76d1b26269630a01a6487f7f004fb9aed228c08d12913c0011a75",
        "authority_role": "P1：跨适应症方案概要、研究流程表、附注和概要表格的次级摘要参照",
    },
    {
        "title": "CMS-D017Ⅰ期方案-v1.1-20260209-clean.docx",
        "sha256": "589ece291e554de81bfc72bea1e29571e896ad0318dd11e2d4906b9f870c3447",
        "authority_role": "P2：完整方案正文、多级标题、目录、页眉页脚和段落样式补充",
    },
    {
        "title": "1-3-4-1-2临床试验方案-V1.1→V1.2-clean(1).docx",
        "sha256": "2cb583af417585b8bd8dcc1f31befb35b1860097909eb65701720d0797c9b082",
        "authority_role": "P2：完整III期方案、表目录、图目录和参考文献样式交叉核验",
    },
]

_PAGE_LAYOUT = {
    "paper": "A4",
    "orientation": "portrait",
    "top_mm": 25.0,
    "bottom_mm": 20.0,
    "left_mm": 25.0,
    "right_mm": 25.0,
    "header_mm": 12.7,
    "footer_mm": 12.7,
    "primary_reference_scope": "CMS-D017-PNH方案摘要v0.2首页及概要正文",
}

_BASE_HEADING = {
    "east_asia": "宋体",
    "latin": "Times New Roman",
    "font_size_pt": 12.0,
    "bold": True,
    "line_height": 1.5,
    "spacing_before_pt": 2.5,
    "spacing_after_pt": 2.5,
    "first_line_indent_chars": 0.0,
    "keep_with_next": True,
}

_STYLE_PRESETS = {
    f"heading_{level}": {**_BASE_HEADING, "heading_level": level}
    for level in range(1, 5)
}
_STYLE_PRESETS.update(
    {
        "body": {
            "east_asia": "宋体",
            "latin": "Times New Roman",
            "font_size_pt": 12.0,
            "bold": False,
            "line_height": 1.5,
            "spacing_before_pt": 0.0,
            "spacing_after_pt": 0.0,
            "first_line_indent_chars": 2.0,
            "keep_with_next": False,
        },
        "note": {
            "east_asia": "宋体",
            "latin": "Times New Roman",
            "font_size_pt": 9.0,
            "bold": False,
            "line_height": 1.5,
            "spacing_before_pt": 0.0,
            "spacing_after_pt": 0.0,
            "first_line_indent_chars": 0.0,
            "keep_with_next": False,
        },
    }
)


class MedicalWritingStyleProfileService:
    def definition(
        self,
        style_profile_id: str = STYLE_PROFILE_ID,
        style_profile_version: str = STYLE_PROFILE_VERSION,
    ) -> MedicalWritingStyleProfileDefinition:
        if (
            style_profile_id != STYLE_PROFILE_ID
            or style_profile_version != STYLE_PROFILE_VERSION
        ):
            raise KeyError(
                "unsupported medical-writing style profile: "
                f"{style_profile_id}/{style_profile_version}"
            )
        payload = {
            "style_profile_id": STYLE_PROFILE_ID,
            "style_profile_version": STYLE_PROFILE_VERSION,
            "authority": (
                "公司中文临床试验方案版式：CMS-D017-PNH方案摘要v0.2为摘要范围最高参照；"
                "D005 clean为次级摘要参照，D017全文和1-3-4-1-2完整方案仅补足全文正文、"
                "标题、目录及参考文献样式。"
            ),
            "country": "CN",
            "language": "zh-CN",
            "source_documents": _SOURCE_DOCUMENTS,
            "page_layout": _PAGE_LAYOUT,
            "style_presets": _STYLE_PRESETS,
        }
        definition_sha256 = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return MedicalWritingStyleProfileDefinition(
            **payload,
            definition_sha256=definition_sha256,
        )
