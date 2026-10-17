"""ClinicalTrials.gov retrieval for the competitor corpus pipeline.

Given a ProjectProfile, builds retrieval strategies from
``query_templates`` (data-configurable), queries the CT.gov API v2
``/studies`` endpoint (same call pattern as
services/api/app/writing_reference.py), and returns a structured candidate
list. Download/parsing of protocol PDFs is NOT part of this module (existing
CT.gov ProvidedDocs download chain covers it).

When the network is unavailable the caller can fall back to
``offline_retrieval`` (synthetic fixture studies, see fixtures.py); the
self-test degrades automatically.

Run:
  python3 tools/corpus/retrieve.py --profile-json '{"drug_name": ...}' --out out.json
  python3 tools/corpus/retrieve.py --profile profile.json --offline --out out.json
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

try:  # package-style import
    from . import query_templates
except ImportError:  # script-style import
    import query_templates

CTGOV_STUDY_URL = query_templates.CTGOV_API_ROOT + "/studies"
USER_AGENT = "protocol-v3-workbench-corpus/1.0 (retrieval only; contact: project owner)"
NCT_ID_RE = re.compile(r"NCT\d{8}")

# Roman-numeral normalisation for CompetitorSet.phase (SCHEMAS §1 uses II|III).
PHASE_ROMAN = {
    "PHASE1": "I",
    "PHASE2": "II",
    "PHASE3": "III",
    "PHASE4": "IV",
}
_PHASE_ORDER = {"PHASE4": 4, "PHASE3": 3, "PHASE2": 2, "PHASE1": 1}


class NetworkUnavailableError(RuntimeError):
    """Network-level failure (DNS, connection, timeout) — caller may degrade."""


class StrategyQueryError(RuntimeError):
    """The API rejected a specific strategy query (HTTP 4xx/5xx, bad JSON).
    Recorded per strategy; other strategies continue."""


def fetch_json(url: str, timeout: float = 30.0) -> dict:
    """GET ``url`` and parse the JSON body.

    HTTP status errors / malformed bodies raise ``StrategyQueryError`` (the
    query itself is the problem); transport-level failures raise
    ``NetworkUnavailableError`` so callers can degrade to offline mode.
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:  # must precede URLError (subclass)
        raise StrategyQueryError(f"HTTP {exc.code} from CT.gov for {url}") from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
        raise NetworkUnavailableError(f"network unavailable: {exc}") from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise StrategyQueryError(f"invalid JSON from CT.gov for {url}") from exc
    if not isinstance(payload, dict):
        raise StrategyQueryError("unexpected CT.gov payload type")
    return payload


def _first_text(container: dict, *keys: str) -> str:
    for key in keys:
        value = str((container or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def normalize_phase(phases: list[str] | None) -> str:
    """['PHASE2','PHASE3'] → 'III' (highest); unknown values kept verbatim."""
    best: tuple[int, str] | None = None
    fallback = ""
    for phase in phases or []:
        upper = str(phase or "").strip().upper()
        if upper in _PHASE_ORDER:
            rank = _PHASE_ORDER[upper]
            if best is None or rank > best[0]:
                best = (rank, PHASE_ROMAN[upper])
        elif upper and not fallback:
            fallback = upper
    if best:
        return best[1]
    return fallback


def _document_flags(study: dict) -> tuple[bool, bool]:
    docs = ((study.get("documentSection") or {}).get("largeDocumentModule") or {}).get(
        "largeDocs"
    ) or []
    has_protocol = False
    has_sap = False
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        abbrev = str(doc.get("typeAbbrev") or "").strip().lower()
        label = str(doc.get("label") or "").strip().lower()
        if doc.get("hasProtocol") or abbrev == "prot" or "protocol" in label:
            has_protocol = True
        if doc.get("hasSap") or abbrev == "sap" or "statistical analysis" in label:
            has_sap = True
    return has_protocol, has_sap


def parse_study(study: dict, matched_strategies: list[str] | None = None) -> dict | None:
    """CT.gov study JSON → structured candidate. Returns None without a valid
    NCT id (recorded as skipped upstream)."""
    protocol = study.get("protocolSection") or {}
    identification = protocol.get("identificationModule") or {}
    nct_id = str(identification.get("nctId") or "").strip()
    if not NCT_ID_RE.fullmatch(nct_id):
        return None
    status = protocol.get("statusModule") or {}
    design = protocol.get("designModule") or {}
    sponsor_module = protocol.get("sponsorCollaboratorsModule") or {}
    lead = sponsor_module.get("leadSponsor") or {}
    conditions = [
        str(item) for item in (protocol.get("conditionsModule") or {}).get("conditions") or []
    ]
    interventions = [
        {"name": str(item.get("name") or ""), "type": str(item.get("type") or "")}
        for item in (protocol.get("armsInterventionsModule") or {}).get("interventions") or []
        if isinstance(item, dict) and (item.get("name") or item.get("type"))
    ]
    enrollment_raw = (design.get("enrollmentInfo") or {}).get("count")
    enrollment = (
        enrollment_raw
        if isinstance(enrollment_raw, int) and not isinstance(enrollment_raw, bool)
        else None
    )
    has_protocol, has_sap = _document_flags(study)
    phases = [str(p) for p in design.get("phases") or []]
    return {
        "study_key": nct_id,
        "title": _first_text(identification, "briefTitle", "officialTitle") or nct_id,
        "phases": phases,
        "phase": normalize_phase(phases),
        "study_type": str(design.get("studyType") or ""),
        "conditions": conditions,
        "interventions": interventions,
        "brief_summary": str(
            (protocol.get("descriptionModule") or {}).get("briefSummary") or ""
        ),
        "lead_sponsor": str(lead.get("name") or ""),
        "sponsor_class": str(lead.get("class") or ""),
        "overall_status": str(status.get("overallStatus") or ""),
        "start_date": str((status.get("startDateStruct") or {}).get("date") or ""),
        "first_posted": str((status.get("studyFirstPostDateStruct") or {}).get("date") or ""),
        "primary_completion_date": str(
            (status.get("primaryCompletionDateStruct") or {}).get("date") or ""
        ),
        "enrollment_count": enrollment,
        "has_protocol_file": has_protocol,
        "has_sap_file": has_sap,
        "matched_strategies": list(matched_strategies or []),
        "source": "ct_gov",
    }


def run_retrieval(
    profile: dict,
    strategies: list[dict] | None = None,
    max_per_strategy: int = 25,
    timeout: float = 30.0,
    fetch: Callable[[str, float], dict] | None = None,
) -> dict:
    """Query CT.gov for every active strategy and merge candidates by NCT id.

    Returns the retrieval envelope written to ``retrieved.json``. Per-strategy
    query errors are recorded in ``strategies``/``gaps``; network-level
    failures raise :class:`NetworkUnavailableError` so the caller can degrade
    to :func:`offline_retrieval`.
    """
    effective = strategies if strategies is not None else query_templates.build_strategies(profile)
    fetcher = fetch or fetch_json
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    strategies_report: list[dict] = []
    gaps: list[dict] = []
    merged: dict[str, dict] = {}
    order: list[str] = []
    skipped_counts: dict[str, int] = {"invalid_nct": 0}

    for strategy in effective:
        strategy_id = strategy.get("strategy_id") or ""
        if strategy.get("skipped"):
            strategies_report.append(
                {
                    "strategy_id": strategy_id,
                    "skipped": True,
                    "skip_reason": strategy.get("skip_reason"),
                    "total": None,
                    "retrieved": 0,
                }
            )
            gaps.append(
                {
                    "kind": "not_retrieved",
                    "where": f"strategy:{strategy_id}",
                    "next": str(strategy.get("skip_reason") or "strategy skipped"),
                }
            )
            continue
        url = query_templates.build_query_url(strategy, page_size=max_per_strategy)
        try:
            payload = fetcher(url, timeout)
        except StrategyQueryError as exc:
            strategies_report.append(
                {
                    "strategy_id": strategy_id,
                    "skipped": False,
                    "error": str(exc),
                    "total": None,
                    "retrieved": 0,
                }
            )
            gaps.append(
                {
                    "kind": "not_retrieved",
                    "where": f"strategy:{strategy_id}",
                    "next": str(exc),
                }
            )
            continue
        total = payload.get("totalCount")
        studies = payload.get("studies") or []
        retrieved = 0
        for study in studies:
            candidate = parse_study(study, [strategy_id])
            if candidate is None:
                skipped_counts["invalid_nct"] += 1
                continue
            key = candidate["study_key"]
            if key in merged:
                existing = merged[key]
                for strategy_name in candidate["matched_strategies"]:
                    if strategy_name not in existing["matched_strategies"]:
                        existing["matched_strategies"].append(strategy_name)
            else:
                merged[key] = candidate
                order.append(key)
                retrieved += 1
        strategies_report.append(
            {
                "strategy_id": strategy_id,
                "skipped": False,
                "query_url": url,
                "total": total,
                "retrieved": retrieved,
            }
        )

    if skipped_counts["invalid_nct"]:
        gaps.append(
            {
                "kind": "not_retrieved",
                "where": "parse",
                "next": f"{skipped_counts['invalid_nct']} study record(s) skipped: invalid nctId",
            }
        )
    return {
        "retrieved_at": now,
        "profile": profile,
        "retrieval_mode": "online",
        "degraded_to_offline": False,
        "strategies": strategies_report,
        "candidates": [merged[key] for key in order],
        "gaps": gaps,
    }


def offline_retrieval(profile: dict) -> dict:
    """Fixture-based retrieval envelope for network-unavailable runs.

    Uses the synthetic fixture studies (fixtures.py) through the exact same
    ``parse_study`` path as online retrieval, so classification/ranking is
    exercised end-to-end without any network access.
    """
    try:  # package-style import
        from . import fixtures
    except ImportError:  # script-style import
        import fixtures

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    candidates = []
    for study in fixtures.fixture_studies_copy():
        nct_id = study["protocolSection"]["identificationModule"]["nctId"]
        candidate = parse_study(study, fixtures.FIXTURE_STRATEGY_HINTS.get(nct_id, []))
        if candidate is not None:
            candidates.append(candidate)
    return {
        "retrieved_at": now,
        "profile": profile,
        "retrieval_mode": "offline_fixture",
        "degraded_to_offline": True,
        "strategies": [
            {
                "strategy_id": "offline_fixtures",
                "skipped": False,
                "query_url": None,
                "total": len(candidates),
                "retrieved": len(candidates),
                "note": "synthetic fixture studies (test data, not live CT.gov records)",
            }
        ],
        "candidates": candidates,
        "gaps": [
            {
                "kind": "not_retrieved",
                "where": "retrieval",
                "next": "network unavailable — results are synthetic fixtures; rerun online for live CT.gov candidates",
            }
        ],
    }


def _load_profile(args: argparse.Namespace) -> dict:
    if args.profile_json:
        profile = json.loads(args.profile_json)
    elif args.profile:
        profile = json.loads(
            open(args.profile, encoding="utf-8").read()  # noqa: SIM115
        )
    else:
        profile = json.loads(sys.stdin.read())
    if not isinstance(profile, dict) or not str(profile.get("drug_name") or "").strip():
        raise SystemExit("profile must be a JSON object with at least drug_name")
    return profile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CT.gov competitor corpus retrieval")
    profile_source = parser.add_mutually_exclusive_group(required=True)
    profile_source.add_argument("--profile-json", help="ProjectProfile as inline JSON")
    profile_source.add_argument("--profile", help="path to ProjectProfile JSON file")
    profile_source.add_argument("--profile-stdin", action="store_true",
                                help="read ProjectProfile JSON from stdin")
    parser.add_argument("--out", help="output JSON path (default: stdout)")
    parser.add_argument("--offline", action="store_true",
                        help="use offline fixture studies instead of the network")
    parser.add_argument("--max-per-strategy", type=int, default=25)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--templates", help="optional JSON file overriding the query templates")
    args = parser.parse_args(argv)

    profile = _load_profile(args)
    templates = None
    if args.templates:
        loaded = json.loads(open(args.templates, encoding="utf-8").read())  # noqa: SIM115
        if not isinstance(loaded, list):
            raise SystemExit("templates file must contain a JSON list")
        templates = loaded

    if args.offline:
        envelope = offline_retrieval(profile)
    else:
        strategies = query_templates.build_strategies(profile, templates)
        envelope = run_retrieval(
            profile,
            strategies=strategies,
            max_per_strategy=max(1, args.max_per_strategy),
            timeout=args.timeout,
        )

    payload = json.dumps(envelope, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        from pathlib import Path

        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
        print(
            f"retrieval: mode={envelope['retrieval_mode']} "
            f"candidates={len(envelope['candidates'])} → {args.out}",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
