"""ChinaDrugTrials (chinadrugtrials.org.cn) secondary-registry client.

The public site sits behind an anti-bot WAF, so automated HTML scrape is not a
reliable production path. This client:

1. Builds a dual-source search intent record (Chinese indication + phase).
2. Attempts a bounded HTTPS probe and classifies outcome.
3. Never invents trial rows when the registry cannot be queried safely.

CT.gov remains the primary executable registry; ChinaDrugTrials results are
attached as secondary provenance / partial_source_failures until a licensed
API or approved scrape path exists.
"""
from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlparse

CHINADRUGTRIALS_HOME = "https://www.chinadrugtrials.org.cn/"
CHINADRUGTRIALS_ALLOWED_HOSTS = frozenset({"www.chinadrugtrials.org.cn", "chinadrugtrials.org.cn"})
USER_AGENT = (
    "WorkbenchMedicalWriting/1.0 (+local; dual-registry research; contact=medical-writing)"
)


@dataclass
class ChinaDrugTrialsSearchIntent:
    indication_zh: str
    study_phase: str
    product_name: str = ""
    query_url: str = ""
    status: str = "planned"
    detail: str = ""
    http_status: int | None = None
    probed_at: str = ""
    trial_hints: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChinaDrugTrialsClient:
    def __init__(self, *, timeout_seconds: int = 20):
        self.timeout_seconds = timeout_seconds

    def build_intent(
        self,
        *,
        indication_zh: str,
        study_phase: str = "",
        product_name: str = "",
    ) -> ChinaDrugTrialsSearchIntent:
        indication = (indication_zh or "").strip()
        phase = (study_phase or "").strip()
        product = (product_name or "").strip()
        # Public listing pages are form-driven; record a discoverable home URL
        # plus structured query parameters for operators / future API binding.
        query = urlencode(
            {
                "indication": indication,
                "phase": phase,
                "product": product,
                "source": "workbench_dual_registry",
            },
            encoding="utf-8",
        )
        return ChinaDrugTrialsSearchIntent(
            indication_zh=indication,
            study_phase=phase,
            product_name=product,
            query_url=f"{CHINADRUGTRIALS_HOME}?{query}",
            status="planned",
            detail="已生成中国药物临床试验登记平台二次检索意图（待可执行接口）。",
            probed_at=datetime.now(timezone.utc).isoformat(),
        )

    def probe_and_search(
        self,
        *,
        indication_zh: str,
        study_phase: str = "",
        product_name: str = "",
    ) -> ChinaDrugTrialsSearchIntent:
        intent = self.build_intent(
            indication_zh=indication_zh,
            study_phase=study_phase,
            product_name=product_name,
        )
        if not intent.indication_zh:
            intent.status = "skipped"
            intent.detail = "适应症为空，跳过中国登记平台二次检索。"
            return intent
        parsed = urlparse(CHINADRUGTRIALS_HOME)
        if parsed.scheme != "https" or parsed.hostname not in CHINADRUGTRIALS_ALLOWED_HOSTS:
            intent.status = "blocked"
            intent.detail = "中国登记平台 URL 不在白名单。"
            return intent
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl.create_default_context())
        )
        request = urllib.request.Request(
            CHINADRUGTRIALS_HOME,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                intent.http_status = getattr(response, "status", None) or response.getcode()
                body = response.read(64_000)
                text = body.decode("utf-8", errors="replace")
                # WAF / challenge pages typically lack a stable public JSON API.
                if "FSSBB" in text or "challenge" in text.lower() or intent.http_status in {202, 403, 429}:
                    intent.status = "waf_blocked"
                    intent.detail = (
                        "中国药物临床试验登记平台返回反爬/挑战页，"
                        "自动抓取不可用；已记录中文适应症二次检索意图，"
                        "请人工在平台核验或待官方接口接入后自动补齐。"
                    )
                    return intent
                intent.status = "reachable_no_api"
                intent.detail = (
                    "平台可达但尚无稳定公开检索 API；"
                    f"已登记查询意图「{intent.indication_zh}」供人工/后续接口执行。"
                )
                return intent
        except urllib.error.HTTPError as exc:
            intent.http_status = exc.code
            intent.status = "http_error"
            intent.detail = f"中国登记平台探测 HTTP {exc.code}：{exc.reason}"
            return intent
        except Exception as exc:  # noqa: BLE001 — surface any probe failure as status
            intent.status = "probe_failed"
            intent.detail = f"中国登记平台探测失败：{type(exc).__name__}: {exc}"
            return intent


def dual_registry_partial_failure(intent: ChinaDrugTrialsSearchIntent) -> str | None:
    """Format a partial_source_failures entry when China registry is not executable."""
    if intent.status in {"reachable_no_api", "waf_blocked", "http_error", "probe_failed", "blocked"}:
        return (
            "chinadrugtrials_secondary:"
            f"{intent.status}:{intent.indication_zh}:{intent.detail[:180]}"
        )
    return None
