from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.medical_monitoring_router import create_medical_monitoring_router
from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
)
from services.api.app.monitoring_rule_authoring_service import (
    MonitoringRuleAuthoringService,
)
from services.api.app.monitoring_rule_lifecycle_service import (
    MonitoringRuleLifecycleService,
)
from tests.test_monitoring_protocol_rules import (
    _fact,
    _publish_pack,
    _rule,
    _start_shadow_pack,
    _version,
)
from tests.test_monitoring_rule_authoring_service import (
    LISTING_ENTRY,
    LISTING_HASH,
    OTHER_PROJECT,
    PROJECT,
    PROTOCOL_ENTRY,
    FakeSourceRegistry,
    _accepted_candidate,
    _template,
)
from services.api.app.monitoring_ai_repository import MonitoringAiRepository


class _EmptyRiskRepository:
    def list_current(self, *_args, **_kwargs):
        return []


def _client(
    service: MonitoringProtocolRuleService | None,
    authoring_service: MonitoringRuleAuthoringService | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_medical_monitoring_router(
            risk_repository=_EmptyRiskRepository(),
            protocol_rule_service=service,
            protocol_rule_authoring_service=authoring_service,
            require_server_principal=False,
        )
    )
    return TestClient(app)


def test_protocol_rule_api_returns_user_facing_source_text_without_internal_hashes() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(Path(directory) / "rules.sqlite3")
        service = MonitoringProtocolRuleService(repository)
        version = repository.register_protocol_version(
            _version(
                "proj_alpha",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        fact = repository.store_fact(_fact(version))
        rule = _rule(version, fact)
        pack = _publish_pack(repository, version, [rule])
        client = _client(service)

        versions = client.get(
            "/api/projects/proj_alpha/modules/medical-monitoring/protocol-versions"
        )
        assert versions.status_code == 200
        assert versions.json()["items"][0]["source_title"] == "proj_alpha 研究方案 V1.0"

        facts = client.get(
            f"/api/projects/proj_alpha/modules/medical-monitoring/"
            f"protocol-versions/{version.protocol_version_id}/facts"
        )
        assert facts.status_code == 200
        assert facts.json()["items"][0]["source_text"] == fact.source_text

        current = client.get(
            "/api/projects/proj_alpha/modules/medical-monitoring/rule-packs/current",
            params={"as_of": "2026-02-01"},
        )
        assert current.status_code == 200
        assert current.json()["rules"][0]["rule_key"] == rule.rule_key

        source = client.get(
            f"/api/projects/proj_alpha/modules/medical-monitoring/"
            f"rule-packs/{pack.rule_pack_id}/rules/{rule.rule_key}/source"
        )
        assert source.status_code == 200
        assert source.json()["source_text"] == fact.source_text
        serialized = source.text + versions.text + facts.text + current.text
        assert "/Users/" not in serialized
        assert '"content_sha256"' not in serialized
        assert "source_text_sha256" not in serialized


def test_protocol_rule_api_fails_closed_for_unconfirmed_applicability() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(Path(directory) / "rules.sqlite3")
        service = MonitoringProtocolRuleService(repository)
        version = repository.register_protocol_version(
            _version("proj_alpha", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        rule = _rule(version, fact)
        _start_shadow_pack(repository, version, [rule])
        client = _client(service)

        response = client.get(
            "/api/projects/proj_alpha/modules/medical-monitoring/rule-packs/current",
            params={"as_of": "2026-02-01"},
        )

        assert response.status_code == 409
        assert (
            response.json()["detail"]["code"]
            == "monitoring_protocol_applicability_unresolved"
        )


def test_protocol_rule_api_is_optional_for_existing_monitoring_mounts() -> None:
    response = _client(None).get(
        "/api/projects/proj_alpha/modules/medical-monitoring/protocol-versions"
    )
    assert response.status_code == 503
    assert (
        response.json()["detail"]["code"]
        == "monitoring_protocol_rules_unavailable"
    )


def test_protocol_rule_api_returns_project_isolated_404_for_unknown_records() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        client = _client(MonitoringProtocolRuleService(repository))
        base = "/api/projects/proj_alpha/modules/medical-monitoring"

        responses = (
            client.get(
                f"{base}/protocol-versions/version-does-not-exist/facts"
            ),
            client.get(f"{base}/rule-packs/pack-does-not-exist"),
            client.get(
                f"{base}/rule-packs/pack-does-not-exist/"
                "rules/rule-does-not-exist/source"
            ),
            client.get(
                f"{base}/rule-packs/pack-does-not-exist/"
                "diff/another-pack-does-not-exist"
            ),
        )

        assert [response.status_code for response in responses] == [
            404,
            404,
            404,
            404,
        ]
        assert [
            response.json()["detail"]["code"]
            for response in responses
        ] == [
            "monitoring_protocol_version_not_found",
            "monitoring_rule_pack_not_found",
            "monitoring_rule_source_not_found",
            "monitoring_rule_pack_diff_not_found",
        ]


def test_protocol_rule_api_does_not_disclose_cross_project_records() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        service = MonitoringProtocolRuleService(repository)
        version = repository.register_protocol_version(
            _version(
                "proj_alpha",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        fact = repository.store_fact(_fact(version))
        rule = _rule(version, fact)
        pack = _publish_pack(repository, version, [rule])
        client = _client(service)
        base = "/api/projects/proj_other/modules/medical-monitoring"

        version_response = client.get(
            f"{base}/protocol-versions/{version.protocol_version_id}/facts"
        )
        pack_response = client.get(f"{base}/rule-packs/{pack.rule_pack_id}")

        assert version_response.status_code == 404
        assert pack_response.status_code == 404


def test_protocol_rule_authoring_api_blocks_incomplete_p7c_release_evidence() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        repository = MonitoringProtocolRuleRepository(root / "rules.sqlite3")
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        ai_repository = MonitoringAiRepository(root / "ai.sqlite3")
        protocol_service = MonitoringProtocolRuleService(repository)
        authoring = MonitoringRuleAuthoringService(
            repository=repository,
            lifecycle_service=MonitoringRuleLifecycleService(
                repository,
                clock=lambda: "2026-07-29T10:00:00+00:00",
            ),
            protocol_rule_service=protocol_service,
            ai_repository=ai_repository,
            source_registry=FakeSourceRegistry(),
        )
        candidate = _accepted_candidate(ai_repository)
        client = _client(protocol_service, authoring)
        base = f"/api/projects/{PROJECT}/modules/medical-monitoring"

        version_response = client.post(
            f"{base}/protocol-versions",
            json={
                "source_entry_id": PROTOCOL_ENTRY,
                "protocol_code": "PROTO-001",
                "version_label": "V1.0",
                "version_date": "2026-07-01",
                "applicability_status": "project_effective_confirmed",
                "operational_effective_from": "2026-07-15",
            },
        )
        assert version_response.status_code == 201
        version_id = version_response.json()["protocol_version"][
            "protocol_version_id"
        ]

        adoption_response = client.post(
            f"{base}/protocol-facts/from-ai-candidate",
            json={
                "protocol_version_id": version_id,
                "candidate_id": candidate.candidate_id,
                "fact_key": "visit_data_completeness",
                "proposed_fact_type": "data_quality",
            },
        )
        assert adoption_response.status_code == 201
        adopted = adoption_response.json()["fact"]
        assert adopted["state"]["label"] == "AI 条款候选已采纳"

        confirmation_response = client.post(
            f"{base}/protocol-facts/{adopted['fact_revision_id']}/confirm",
            json={
                "expected_state_version": adopted["state_version"],
                "fact_type": "data_quality",
                "deterministic_template": _template(),
                "confirmed_by": "medical_manager",
            },
        )
        assert confirmation_response.status_code == 200
        confirmed_fact = confirmation_response.json()["fact"]
        assert confirmed_fact["state"]["label"] == "医学经理已确认"

        draft_response = client.post(
            f"{base}/rule-packs/drafts",
            json={
                "protocol_version_id": version_id,
                "fact_revision_ids": [confirmed_fact["fact_revision_id"]],
                "created_by": "medical_manager",
            },
        )
        assert draft_response.status_code == 201
        draft = draft_response.json()
        draft_id = draft["pack"]["rule_pack_id"]
        rule_id = draft["rules"][0]["rule_revision_id"]

        direct_publish = client.post(
            f"{base}/rule-packs/{draft_id}/publish",
            json={"actor": "medical_manager"},
        )
        assert direct_publish.status_code == 409

        rule_confirmation = client.post(
            f"{base}/rule-packs/{draft_id}/rules/{rule_id}/confirm",
            json={
                "expected_state_version": 1,
                "confirmed_by": "medical_manager",
            },
        )
        # The recommendation-adopted rule is already confirmed; a second
        # per-rule medical approval is structurally refused.
        assert rule_confirmation.status_code == 409

        shadow_response = client.post(
            f"{base}/rule-packs/{draft_id}/start-shadow",
            json={"actor": "medical_manager"},
        )
        assert shadow_response.status_code == 200
        shadow_id = shadow_response.json()["pack"]["rule_pack_id"]

        no_gold = client.post(
            f"{base}/rule-packs/{shadow_id}/shadow-runs",
            json={"batch_id": "shadow-batch"},
        )
        assert no_gold.status_code == 409

        locator = f"listing:{LISTING_HASH}:sheet:LB:row:2"
        gold_case = authoring.register_gold_case(
            project_id=PROJECT,
            rule_pack_id=shadow_id,
            rule_revision_id=rule_id,
            source_entry_id=LISTING_ENTRY,
            source_revision="source-revision-1",
            batch_revision="batch-revision-1",
            case_label="访视数据完整性阳性核对案例",
            input_record={
                "SUBJID": "001",
                "REVIEW_FLAG": "CHECK",
                "__source_locator__": locator,
            },
            observed_domains=["LB"],
            expected_match=True,
            medical_rationale="真实 listing 行满足确定性条件。",
            evidence_locators=[locator],
            source_row_bindings=[
                {
                    "business_key": "SUBJID=001|LB|row=2",
                    "domain": "LB",
                    "source_locator": locator,
                    "row_fingerprint": "c" * 64,
                    "record_roles": ["current"],
                    "field_bindings": [
                        {
                            "record_role": "current",
                            "record_field": "SUBJID",
                            "source_field": "SUBJID",
                        },
                        {
                            "record_role": "current",
                            "record_field": "REVIEW_FLAG",
                            "source_field": "REVIEW_FLAG",
                        },
                    ],
                }
            ],
        )
        assert list(gold_case.coverage_labels) == ["positive"]

        boundary_locator = f"listing:{LISTING_HASH}:sheet:LB:row:3"
        boundary_case = authoring.register_gold_case(
            project_id=PROJECT,
            rule_pack_id=shadow_id,
            rule_revision_id=rule_id,
            source_entry_id=LISTING_ENTRY,
            source_revision="source-revision-1",
            batch_revision="batch-revision-1",
            case_label="访视数据完整性边界核对案例",
            input_record={
                "SUBJID": "002",
                "REVIEW_FLAG": "NO_CHECK",
                "__source_locator__": boundary_locator,
            },
            observed_domains=["LB"],
            expected_match=False,
            coverage_labels=["negative", "boundary"],
            medical_rationale="真实 listing 行位于预先定义的规则边界。",
            evidence_locators=[boundary_locator],
            source_row_bindings=[
                {
                    "business_key": "SUBJID=002|LB|row=3",
                    "domain": "LB",
                    "source_locator": boundary_locator,
                    "row_fingerprint": "d" * 64,
                    "record_roles": ["current"],
                    "field_bindings": [
                        {
                            "record_role": "current",
                            "record_field": "SUBJID",
                            "source_field": "SUBJID",
                        },
                        {
                            "record_role": "current",
                            "record_field": "REVIEW_FLAG",
                            "source_field": "REVIEW_FLAG",
                        },
                    ],
                }
            ],
        )
        assert list(boundary_case.coverage_labels) == [
            "boundary",
            "negative",
        ]

        diagnostic_locator = f"listing:{LISTING_HASH}:sheet:ZZ:row:4"
        diagnostic_case = authoring.register_diagnostic_case(
            project_id=PROJECT,
            rule_pack_id=shadow_id,
            rule_revision_id=rule_id,
            source_entry_id=LISTING_ENTRY,
            source_revision="source-revision-1",
            batch_revision="batch-revision-1",
            case_label="缺少规则必需数据域",
            input_record={
                "SUBJID": "003",
                "__source_locator__": diagnostic_locator,
            },
            observed_domains=["ZZ"],
            expected_diagnostic_category="missing_input",
            expected_diagnostic_code="missing_required_domains",
            medical_rationale="真实 listing 输入缺少规则必需域，必须返回不可判定。",
            evidence_locators=[diagnostic_locator],
            source_row_bindings=[
                {
                    "business_key": "SUBJID=003|ZZ|row=4",
                    "domain": "ZZ",
                    "source_locator": diagnostic_locator,
                    "row_fingerprint": "e" * 64,
                    "record_roles": ["current"],
                    "field_bindings": [
                        {
                            "record_role": "current",
                            "record_field": "SUBJID",
                            "source_field": "SUBJID",
                        }
                    ],
                }
            ],
        )
        assert diagnostic_case.expected_diagnostic_category == "missing_input"
        assert diagnostic_case.expected_diagnostic_code == "missing_required_domains"

        shadow_run_response = client.post(
            f"{base}/rule-packs/{shadow_id}/shadow-runs",
            json={"batch_id": "shadow-batch"},
        )
        assert shadow_run_response.status_code == 201
        shadow_run = shadow_run_response.json()["shadow_run"]
        assert shadow_run["failed_count"] == 0

        shadow_confirmation = client.post(
            f"{base}/rule-packs/{shadow_id}/confirm-shadow",
            json={
                "shadow_run_id": shadow_run["shadow_run_id"],
                "confirmed_by": "medical_manager",
            },
        )
        assert shadow_confirmation.status_code == 200
        confirmed_pack_id = shadow_confirmation.json()["pack"]["rule_pack_id"]

        publish_response = client.post(
            f"{base}/rule-packs/{confirmed_pack_id}/publish",
            json={"actor": "medical_manager"},
        )
        assert publish_response.status_code == 200
        assert publish_response.json()["state"]["label"] == "规则包已发布"
        serialized = "\n".join(
            response.text
            for response in (
                version_response,
                adoption_response,
                confirmation_response,
                draft_response,
                shadow_run_response,
                publish_response,
            )
        )
        assert '"content_sha256"' not in serialized
        assert "source_text_sha256" not in serialized
        assert "待医学批准" not in serialized


def test_protocol_applicability_api_is_exact_auditable_and_fail_closed() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        repository = MonitoringProtocolRuleRepository(root / "rules.sqlite3")
        ai_repository = MonitoringAiRepository(root / "ai.sqlite3")
        protocol_service = MonitoringProtocolRuleService(repository)
        authoring = MonitoringRuleAuthoringService(
            repository=repository,
            lifecycle_service=MonitoringRuleLifecycleService(repository),
            protocol_rule_service=protocol_service,
            ai_repository=ai_repository,
            source_registry=FakeSourceRegistry(),
        )
        client = _client(protocol_service, authoring)
        base = f"/api/projects/{PROJECT}/modules/medical-monitoring"
        version_response = client.post(
            f"{base}/protocol-versions",
            json={
                "source_entry_id": PROTOCOL_ENTRY,
                "protocol_code": "PROTO-001",
                "version_label": "V2.0",
                "version_date": "2026-07-20",
                "applicability_status": "site_specific",
            },
        )
        assert version_response.status_code == 201
        version_id = version_response.json()["protocol_version"][
            "protocol_version_id"
        ]
        create_response = client.post(
            f"{base}/protocol-applicability-assignments",
            json={
                "protocol_version_id": version_id,
                "centre_id": "001",
                "subject_id": "0007",
                "operational_effective_from": "2026-07-21",
                "operational_effective_to": "2026-12-31",
                "evidence_text": "中心确认该受试者自所列日期起执行 V2.0。",
                "evidence_source_entry_id": PROTOCOL_ENTRY,
                "evidence_locator": "docx:paragraph:150",
                "created_by": "medical_manager",
            },
        )
        assert create_response.status_code == 201
        candidate = create_response.json()["assignment"]
        assert candidate["centre_id"] == "001"
        assert candidate["subject_id"] == "0007"
        assert create_response.text.index("evidence_text") < create_response.text.index(
            "evidence_locator"
        )
        assert "sha256" not in create_response.text.lower()

        unresolved = client.get(
            f"{base}/protocol-applicability-assignments/resolve",
            params={
                "centre_id": "001",
                "subject_id": "0007",
                "event_date": "2026-07-22",
            },
        )
        assert unresolved.status_code == 409
        assert (
            unresolved.json()["detail"]["code"]
            == "monitoring_protocol_applicability_unresolved"
        )
        confirm = client.post(
            f"{base}/protocol-applicability-assignments/"
            f"{candidate['assignment_id']}/confirm",
            json={
                "expected_state_version": candidate["state_version"],
                "confirmed_by": "medical_manager",
            },
        )
        assert confirm.status_code == 200
        resolved = client.get(
            f"{base}/protocol-applicability-assignments/resolve",
            params={
                "centre_id": "001",
                "subject_id": "0007",
                "event_date": "2026-07-22",
            },
        )
        assert resolved.status_code == 200
        assert resolved.json()["protocol_version_id"] == version_id
        assert resolved.json()["assignment"]["subject_id"] == "0007"
        wrong_exact_id = client.get(
            f"{base}/protocol-applicability-assignments/resolve",
            params={
                "centre_id": "1",
                "subject_id": "7",
                "event_date": "2026-07-22",
            },
        )
        assert wrong_exact_id.status_code == 409

        cross_project = client.post(
            f"/api/projects/{OTHER_PROJECT}/modules/medical-monitoring/"
            f"protocol-applicability-assignments/{candidate['assignment_id']}/confirm",
            json={
                "expected_state_version": 2,
                "confirmed_by": "medical_manager",
            },
        )
        assert cross_project.status_code == 404
        stale = client.post(
            f"{base}/protocol-applicability-assignments/"
            f"{candidate['assignment_id']}/retire",
            json={
                "expected_state_version": 1,
                "retired_by": "medical_manager",
            },
        )
        assert stale.status_code == 409
        retire = client.post(
            f"{base}/protocol-applicability-assignments/"
            f"{candidate['assignment_id']}/retire",
            json={
                "expected_state_version": 2,
                "retired_by": "medical_manager",
            },
        )
        assert retire.status_code == 200
        assert retire.json()["assignment"]["status"] == "retired"


def test_rule_pack_draft_api_replays_identical_creation() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        repository = MonitoringProtocolRuleRepository(root / "rules.sqlite3")
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        ai_repository = MonitoringAiRepository(root / "ai.sqlite3")
        protocol_service = MonitoringProtocolRuleService(repository)
        authoring = MonitoringRuleAuthoringService(
            repository=repository,
            lifecycle_service=MonitoringRuleLifecycleService(
                repository,
                clock=lambda: "2026-07-29T10:00:00+00:00",
            ),
            protocol_rule_service=protocol_service,
            ai_repository=ai_repository,
            source_registry=FakeSourceRegistry(),
        )
        candidate = _accepted_candidate(ai_repository)
        client = _client(protocol_service, authoring)
        base = f"/api/projects/{PROJECT}/modules/medical-monitoring"

        version_response = client.post(
            f"{base}/protocol-versions",
            json={
                "source_entry_id": PROTOCOL_ENTRY,
                "protocol_code": "PROTO-001",
                "version_label": "V1.0",
                "version_date": "2026-07-01",
                "applicability_status": "project_effective_confirmed",
                "operational_effective_from": "2026-07-15",
            },
        )
        assert version_response.status_code == 201
        version_id = version_response.json()["protocol_version"][
            "protocol_version_id"
        ]
        adoption_response = client.post(
            f"{base}/protocol-facts/from-ai-candidate",
            json={
                "protocol_version_id": version_id,
                "candidate_id": candidate.candidate_id,
                "fact_key": "visit_data_completeness",
                "proposed_fact_type": "data_quality",
            },
        )
        assert adoption_response.status_code == 201
        adopted = adoption_response.json()["fact"]
        confirmation_response = client.post(
            f"{base}/protocol-facts/{adopted['fact_revision_id']}/confirm",
            json={
                "expected_state_version": adopted["state_version"],
                "fact_type": "data_quality",
                "deterministic_template": _template(),
                "confirmed_by": "medical_manager",
            },
        )
        assert confirmation_response.status_code == 200
        confirmed_fact = confirmation_response.json()["fact"]

        draft_body = {
            "protocol_version_id": version_id,
            "fact_revision_ids": [confirmed_fact["fact_revision_id"]],
            "created_by": "medical_manager",
        }
        first = client.post(f"{base}/rule-packs/drafts", json=draft_body)
        assert first.status_code == 201
        assert first.json()["reused"] is False

        second = client.post(f"{base}/rule-packs/drafts", json=draft_body)
        assert second.status_code == 200
        assert second.json()["reused"] is True
        assert (
            second.json()["pack"]["rule_pack_id"]
            == first.json()["pack"]["rule_pack_id"]
        )

        stale = client.post(
            f"{base}/rule-packs/drafts",
            json={**draft_body, "expected_pack_revision": 99},
        )
        assert stale.status_code == 409

        matched = client.post(
            f"{base}/rule-packs/drafts",
            json={
                **draft_body,
                "expected_pack_revision": first.json()["pack"]["pack_revision"],
            },
        )
        assert matched.status_code == 200
        assert matched.json()["reused"] is True
        assert (
            matched.json()["pack"]["rule_pack_id"]
            == first.json()["pack"]["rule_pack_id"]
        )


def test_confirm_shadow_requires_exactly_one_target() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        repository = MonitoringProtocolRuleRepository(root / "rules.sqlite3")
        protocol_service = MonitoringProtocolRuleService(repository)
        authoring = MonitoringRuleAuthoringService(
            repository=repository,
            lifecycle_service=MonitoringRuleLifecycleService(repository),
            protocol_rule_service=protocol_service,
            ai_repository=MonitoringAiRepository(root / "ai.sqlite3"),
            source_registry=FakeSourceRegistry(),
        )
        client = _client(protocol_service, authoring)
        base = f"/api/projects/{PROJECT}/modules/medical-monitoring"
        url = f"{base}/rule-packs/monpack_any/confirm-shadow"

        neither = client.post(
            url,
            json={"confirmed_by": "medical_manager"},
        )
        assert neither.status_code == 409
        assert neither.json()["detail"]["code"] == (
            "monitoring_shadow_confirmation_target_invalid"
        )

        both = client.post(
            url,
            json={
                "shadow_run_id": "monshrun_any",
                "sample_set_id": "monshsample_any",
                "confirmed_by": "medical_manager",
            },
        )
        assert both.status_code == 409
        assert both.json()["detail"]["code"] == (
            "monitoring_shadow_confirmation_target_invalid"
        )
