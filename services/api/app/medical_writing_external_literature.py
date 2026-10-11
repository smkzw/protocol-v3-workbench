"""背景自主外查服务（P0-2，owner 裁定 20261001 + 两次补充）。

owner 规则：疾病背景/流行病学/指南/治疗现状类内容不得作为 source_gap
阻断——外查优先、失败才降级 source_gap；研究药物自身数据边界不变
（剂量/IB/既往临床等药物特异缺失仍走 source_gap，不得用外查顶替）。

本模块提供：
- PubMed E-utilities 检索客户端（esearch 出 PMID 集、efetch 取全文元数据），
  真实 PMID 可回验（efetch 返回集必须覆盖请求 PMID，缺失即剔除并留痕），
  检索原文逐次留档（esearch JSON / efetch XML 原字节落盘）；
- 元数据落库（sqlite external_literature_records，PMID 唯一）；
- 参考文献双格式纯代码渲染（Vancouver 默认 / GB-T 7714 可选；期刊缩写用
  NLM TA 字段，缺失保留全称；同一输入两次渲染逐字一致）；
- 知网显式标注 cnki_not_integrated，不做硬集成。

网络传输经可注入的 fetch 函数隔离，离线测试用夹具回放。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DEFAULT_EXTERNAL_CITATION_STYLE = "vancouver"
SUPPORTED_EXTERNAL_CITATION_STYLES = ("vancouver", "gbt_7714_2015_numeric")
SOURCE_INTEGRATION_STATUS = {
    "pubmed": "integrated",
    "cnki": "cnki_not_integrated",
}


class ExternalLiteratureError(ValueError):
    """外查服务契约错误（422 族）。"""


class ExternalLiteratureNotIntegratedError(ExternalLiteratureError):
    """来源未集成（如知网）：显式拒绝，不做硬集成。"""


def source_integration_status(source: str) -> str:
    status = SOURCE_INTEGRATION_STATUS.get(str(source or "").strip().lower())
    if status is None:
        raise ExternalLiteratureError(f"未知外部文献来源：{source}")
    return status


def require_source_integrated(source: str) -> None:
    status = source_integration_status(source)
    if status != "integrated":
        raise ExternalLiteratureNotIntegratedError(
            f"外部来源 {source} 当前状态为 {status}，未做硬集成；"
            "相关内容请走项目语料或人工补充。"
        )


def pmid_is_wellformed(pmid: str) -> bool:
    """PMID 解析体检：纯数字且不为 0/超长（>9 位现网不存在）。"""
    candidate = str(pmid or "").strip()
    return bool(re.fullmatch(r"[1-9][0-9]{0,8}", candidate))


@dataclass(frozen=True)
class ExternalLiteratureRecord:
    pmid: str
    title: str
    journal: str
    journal_ta: str = ""
    pub_year: str = ""
    authors: tuple[str, ...] = field(default_factory=tuple)
    doi: str = ""

    def journal_display(self) -> str:
        """期刊缩写用 NLM TA 字段；缺失保留全称（owner 三件套②）。"""
        return self.journal_ta.strip() or self.journal.strip()

    def identity_sha256(self) -> str:
        canonical = json.dumps(
            {
                "pmid": self.pmid,
                "title": self.title.strip(),
                "journal": self.journal.strip(),
                "pub_year": self.pub_year.strip(),
                "doi": self.doi.strip(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _text_of(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def parse_pubmed_efetch_xml(xml_text: str) -> dict[str, ExternalLiteratureRecord]:
    """efetch XML → 规范化记录（纯解析，可离线回放测试）。"""
    root = ET.fromstring(xml_text)
    records: dict[str, ExternalLiteratureRecord] = {}
    for article in root.iter("PubmedArticle"):
        pmid = _text_of(article.find("./MedlineCitation/PMID"))
        if not pmid_is_wellformed(pmid):
            continue
        article_node = article.find("./MedlineCitation/Article")
        title = _text_of(article_node.find("ArticleTitle")) if article_node is not None else ""
        journal_node = article_node.find("Journal") if article_node is not None else None
        journal = _text_of(journal_node.find("Title")) if journal_node is not None else ""
        journal_ta = _text_of(journal_node.find("ISOAbbreviation")) if journal_node is not None else ""
        pub_year = _text_of(journal_node.find("JournalIssue/PubDate/Year")) if journal_node is not None else ""
        if not pub_year and journal_node is not None:
            pub_year = _text_of(journal_node.find("JournalIssue/PubDate/MedlineDate"))[:4]
        authors: list[str] = []
        for author in article.iter("Author"):
            last = _text_of(author.find("LastName"))
            initials = _text_of(author.find("Initials"))
            if last:
                authors.append(f"{last} {initials}".strip())
        doi = ""
        for eid in article.iter("ArticleId"):
            if (eid.get("IdType") or "") == "doi":
                doi = _text_of(eid)
                break
        records[pmid] = ExternalLiteratureRecord(
            pmid=pmid,
            title=title,
            journal=journal,
            journal_ta=journal_ta,
            pub_year=pub_year,
            authors=tuple(authors),
            doi=doi,
        )
    return records


class PubMedEUtilsClient:
    """PubMed E-utilities 检索客户端（检索原文逐次留档）。"""

    def __init__(
        self,
        *,
        archive_dir: Path,
        timeout_seconds: int = 20,
        fetch_json: Callable[[str], dict[str, Any]] | None = None,
        fetch_text: Callable[[str], str] | None = None,
    ):
        self._archive_dir = Path(archive_dir)
        self._timeout_seconds = timeout_seconds
        self._fetch_json = fetch_json or self._default_fetch_json
        self._fetch_text = fetch_text or self._default_fetch_text

    @staticmethod
    def _default_fetch_json(url: str) -> dict[str, Any]:
        with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _default_fetch_text(url: str) -> str:
        with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310
            return response.read().decode("utf-8")

    def _archive(self, kind: str, query_key: str, body: str, suffix: str) -> str:
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
        path = self._archive_dir / f"{kind}_{stamp}_{query_key}_{digest}{suffix}"
        path.write_text(body, encoding="utf-8")
        return str(path)

    def search(self, query: str, *, retmax: int = 5) -> dict[str, Any]:
        term = urllib.parse.quote(str(query or "").strip())
        if not term:
            raise ExternalLiteratureError("外查检索词为空")
        url = f"{EUTILS_BASE}/esearch.fcgi?db=pubmed&term={term}&retmode=json&retmax={int(retmax)}"
        raw = json.dumps(self._fetch_json(url), ensure_ascii=False, sort_keys=True)
        payload = json.loads(raw)
        try:
            esearch = payload["esearchresult"]
            pmids = [str(item) for item in esearch.get("idlist") or []]
        except (KeyError, TypeError) as exc:
            raise ExternalLiteratureError("PubMed esearch 响应结构无效") from exc
        verified = [pmid for pmid in pmids if pmid_is_wellformed(pmid)]
        archive_path = self._archive("esearch", hashlib.sha256(term.encode("utf-8")).hexdigest()[:10], raw, ".json")
        return {
            "query": query,
            "pmids": verified,
            "dropped_malformed_pmids": [pmid for pmid in pmids if pmid not in verified],
            "count": len(verified),
            "raw_archive_path": archive_path,
        }

    def fetch_records(self, pmids: list[str]) -> dict[str, Any]:
        """efetch 取元数据；真实 PMID 可回验——返回集必须来自响应原文。"""
        cleaned = [str(pmid).strip() for pmid in pmids if pmid_is_wellformed(pmid)]
        dropped = [str(pmid).strip() for pmid in pmids if not pmid_is_wellformed(pmid)]
        if not cleaned:
            return {"records": {}, "dropped_malformed_pmids": dropped, "missing_pmids": [], "raw_archive_path": ""}
        ids = ",".join(cleaned)
        url = f"{EUTILS_BASE}/efetch.fcgi?db=pubmed&id={ids}&retmode=xml"
        xml_text = self._fetch_text(url)
        archive_path = self._archive("efetch", hashlib.sha256(ids.encode("utf-8")).hexdigest()[:10], xml_text, ".xml")
        parsed = parse_pubmed_efetch_xml(xml_text)
        missing = [pmid for pmid in cleaned if pmid not in parsed]
        return {
            "records": parsed,
            "dropped_malformed_pmids": dropped,
            "missing_pmids": missing,
            "raw_archive_path": archive_path,
        }


class ExternalLiteratureArchive:
    """元数据落库（sqlite，PMID 唯一）+ 检索原文路径留档。"""

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS external_literature_records(
                    pm_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    journal TEXT NOT NULL,
                    journal_ta TEXT NOT NULL,
                    pub_year TEXT NOT NULL,
                    authors_json TEXT NOT NULL,
                    doi TEXT NOT NULL,
                    identity_sha256 TEXT NOT NULL,
                    raw_esearch_path TEXT NOT NULL DEFAULT '',
                    raw_efetch_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )

    def upsert_records(
        self,
        records: dict[str, ExternalLiteratureRecord],
        *,
        raw_esearch_path: str = "",
        raw_efetch_path: str = "",
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        written = 0
        with self._connect() as connection:
            for pmid, record in records.items():
                connection.execute(
                    """
                    INSERT INTO external_literature_records(
                        pm_id, title, journal, journal_ta, pub_year,
                        authors_json, doi, identity_sha256,
                        raw_esearch_path, raw_efetch_path, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(pm_id) DO UPDATE SET
                        title=excluded.title, journal=excluded.journal,
                        journal_ta=excluded.journal_ta, pub_year=excluded.pub_year,
                        authors_json=excluded.authors_json, doi=excluded.doi,
                        identity_sha256=excluded.identity_sha256,
                        raw_efetch_path=excluded.raw_efetch_path
                    """,
                    (
                        record.pmid,
                        record.title,
                        record.journal,
                        record.journal_ta,
                        record.pub_year,
                        json.dumps(list(record.authors), ensure_ascii=False),
                        record.doi,
                        record.identity_sha256(),
                        raw_esearch_path,
                        raw_efetch_path,
                        now,
                    ),
                )
                written += 1
        return written

    def get(self, pmid: str) -> ExternalLiteratureRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM external_literature_records WHERE pm_id = ?",
                (str(pmid).strip(),),
            ).fetchone()
        if row is None:
            return None
        return ExternalLiteratureRecord(
            pmid=row["pm_id"],
            title=row["title"],
            journal=row["journal"],
            journal_ta=row["journal_ta"],
            pub_year=row["pub_year"],
            authors=tuple(json.loads(row["authors_json"])),
            doi=row["doi"],
        )


# ── 参考文献纯代码渲染（角标与文末列表同源；禁止模型写引文文本） ────────────


def citation_marker(number: int) -> str:
    return f"[{int(number)}]"


def format_reference_vancouver(number: int, record: ExternalLiteratureRecord) -> str:
    authors = [item.strip() for item in record.authors if item.strip()]
    if not authors:
        author_text = "Anonymous"
    elif len(authors) <= 6:
        author_text = ", ".join(authors)
    else:
        author_text = f"{', '.join(authors[:6])}, et al"
    parts = [f"[{number}]"]
    parts.append(f"{author_text}. {record.title.strip() or '题名缺失'}.")
    journal = record.journal_display()
    tail = f" {record.pub_year.strip()}" if record.pub_year.strip() else ""
    if record.doi.strip():
        tail += f". DOI: {record.doi.strip()}."
    parts.append(f"{journal}.{tail}")
    return " ".join(part for part in parts if part)


def format_reference_gbt7714(number: int, record: ExternalLiteratureRecord) -> str:
    authors = [item.strip() for item in record.authors if item.strip()]
    if not authors:
        author_text = "佚名"
    elif len(authors) <= 3:
        author_text = ", ".join(authors)
    else:
        author_text = f"{', '.join(authors[:3])}, 等"
    journal = record.journal_display()
    year = record.pub_year.strip()
    tail = f", {year}" if year else ""
    if record.doi.strip():
        tail += f". DOI: {record.doi.strip()}."
    else:
        tail += "."
    return f"[{number}] {author_text}. {record.title.strip() or '题名缺失'}[J]. {journal}{tail}"


def render_reference_list(
    records: list[ExternalLiteratureRecord],
    style: str = DEFAULT_EXTERNAL_CITATION_STYLE,
) -> list[str]:
    """文末列表纯代码渲染；双格式确定性——同输入两次渲染逐字一致。"""
    if style not in SUPPORTED_EXTERNAL_CITATION_STYLES:
        raise ExternalLiteratureError(
            f"不支持的参考文献格式：{style}（可选：" + "、".join(SUPPORTED_EXTERNAL_CITATION_STYLES) + "）"
        )
    formatter = {
        "vancouver": format_reference_vancouver,
        "gbt_7714_2015_numeric": format_reference_gbt7714,
    }[style]
    ordered = sorted(records, key=lambda item: int(item.pmid))
    return [formatter(number, record) for number, record in enumerate(ordered, start=1)]


_BIBLIOGRAPHY_LINE_RE = re.compile(
    r"^\s*(?:\[\s*\d{1,3}\s*\]|\d{1,3}[.、])\s+\S.{8,}\.(?:\s*DOI:.*)?$"
)


def model_authored_bibliography_lines(text: str) -> list[str]:
    """体检：模型正文里自写的文末式引文行（角标与列表必须纯代码渲染）。"""
    hits = []
    for line in str(text or "").splitlines():
        if _BIBLIOGRAPHY_LINE_RE.match(line):
            hits.append(line.strip())
    return hits


def attach_citation_markers(text: str, section_pmids: list[str]) -> str:
    """把本节引用的 PMID 序列转成正文角标（纯代码，顺序即传入顺序）。"""
    cleaned = [str(pmid).strip() for pmid in section_pmids if pmid_is_wellformed(pmid)]
    if not cleaned:
        return str(text or "")
    markers = "".join(citation_marker(index) for index in range(1, len(cleaned) + 1))
    return f"{str(text or '').rstrip()}（外部文献核查：{markers}）"


# ── 背景章外查降级规则（外查优先、失败才降级 source_gap） ────────────────────

BACKGROUND_HEADING_RE = re.compile(
    r"研究背景|疾病背景|背景与立题|治疗现状|治疗格局|流行病学"
)
_BACKGROUND_GAP_CLASSES = {
    "epidemiology": "流行病学",
    "guidelines": "指南",
    "disease_burden": "疾病负担",
    "treatment_landscape": "治疗现状",
}
_DRUG_SPECIFIC_CLASSES = {
    "ib": "研究药物IB",
    "investigational_product": "研究药物资料",
    "nonclinical": "非临床资料",
    "prior_clinical": "既往临床资料",
}


def background_gap_classes_overridable(missing_source_classes: list[str]) -> bool:
    """缺的来源类全部落在背景外查可覆盖族内（药物特异类永不覆盖）。"""
    classes = {str(item or "").strip().lower() for item in missing_source_classes or []}
    if not classes:
        return False
    if classes & set(_DRUG_SPECIFIC_CLASSES):
        return False
    return classes.issubset(set(_BACKGROUND_GAP_CLASSES))


def external_lookup_outcome(
    *,
    status: str,
    records: list[ExternalLiteratureRecord] | None = None,
    note: str = "",
) -> dict[str, Any]:
    """外查结果契约：hit（有命中）/ failed（检索失败或空结果）/ not_attempted。"""
    if status not in {"hit", "failed", "not_attempted"}:
        raise ExternalLiteratureError(f"外查结果状态无效：{status}")
    return {
        "status": status,
        "records": [
            {
                "pmid": record.pmid,
                "title": record.title,
                "journal": record.journal_display(),
                "pub_year": record.pub_year,
            }
            for record in (records or [])
        ],
        "note": note,
    }


def apply_background_external_lookup(
    section_item: dict,
    lookup: dict[str, Any],
) -> None:
    """生成层背景章降级规则（就地修改 section_item）。

    - 章节为背景类且模型判 source_gap、缺的来源类全部属背景外查可覆盖族
      且外查 hit → 降级解除：改判 partial，附外部文献命中留痕（候选绑定：
      PMID 记入 evidence_bindings 之外的绑定说明），不阻断主线；
    - 外查 failed/not_attempted → 维持 source_gap（诚实降级）；
    - 药物特异类缺失 → 无论外查结果一律维持（研究药物自身数据边界不变）。
    """
    heading = str(section_item.get("heading") or "")
    if not BACKGROUND_HEADING_RE.search(heading):
        return
    if str(section_item.get("content_status")) != "source_gap":
        return
    missing = [str(item or "") for item in section_item.get("missing_source_classes") or []]
    if not background_gap_classes_overridable(missing):
        return
    if str(lookup.get("status")) != "hit":
        section_item["background_external_lookup"] = {
            "status": str(lookup.get("status")),
            "note": str(lookup.get("note") or "外查未命中，维持来源缺口判定"),
        }
        return
    records = [
        {
            "pmid": str(item.get("pmid") or ""),
            "title": str(item.get("title") or ""),
            "journal": str(item.get("journal") or ""),
        }
        for item in lookup.get("records") or []
        if pmid_is_wellformed(str(item.get("pmid") or ""))
    ]
    section_item["content_status"] = "partial"
    section_item["background_external_lookup"] = {
        "status": "hit",
        "records": records,
        "note": str(lookup.get("note") or "背景外查命中，来源缺口降级为待融合撰写的部分内容"),
    }
    proposal = str(section_item.get("proposal_text") or "")
    marker_note = (
        f"（背景外查命中 {len(records)} 篇（PMID: "
        + "、".join(item['pmid'] for item in records)
        + "）；正文待按综述三步法融合后重评。）"
    )
    section_item["proposal_text"] = (proposal + marker_note).strip()
