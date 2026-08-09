from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, Iterable, Protocol

from packages.contracts.workbench_contracts import RiskCase
from packages.contracts.workbench_contracts.models import SubjectMonitoringDrilldown

from .monitoring_mapping_activation import (
    MonitoringMappingActivationNotFoundError,
    MonitoringMappingCapabilityUnavailableError,
)


class MonitoringProjectCapabilityUnavailableError(RuntimeError):
    pass


class MonitoringProjectAdapter(Protocol):
    def subject_ids(self) -> list[str]: ...

    def subject_catalog(self, project_id: str) -> Dict[str, Any]: ...

    def subject_monitoring(self, project_id: str, subject_id: str) -> SubjectMonitoringDrilldown: ...

    def source_revision(self) -> str: ...

    def evaluate_subject_risks(self, project_id: str, subject_id: str) -> list[RiskCase]: ...

    def protocol_rule_registry(self) -> Dict[str, list[Dict[str, Any]]]: ...

    def risk_profile_revision(self) -> str: ...

    def risk_engine_version(self) -> str: ...

    def risk_resolution_complete(self) -> bool: ...

    def resolve_source_fragment(self, locator: str) -> Dict[str, Any]: ...


@dataclass(frozen=True)
class BoundMonitoringProjectAdapter:
    project_id: str
    service: MonitoringProjectAdapter
    risk_subject_ids: tuple[str, ...] = ()
    capability_resolver: Callable[[str, str], Any] | None = None

    def subject_ids(self) -> list[str]:
        return self.service.subject_ids()

    def subject_catalog(self) -> Dict[str, Any]:
        source_revision = self.source_revision()
        catalog = self.service.subject_catalog(self.project_id)
        self._assert_project(catalog.get("project_id"))
        self._assert_stable_source_revision(
            source_revision,
            reported_revision=catalog.get("source_revision"),
        )
        return catalog

    def subject_monitoring(self, subject_id: str) -> SubjectMonitoringDrilldown:
        source_revision = self.source_revision()
        profile = self.service.subject_monitoring(self.project_id, subject_id)
        self._assert_project(profile.project_id)
        self._assert_stable_source_revision(
            source_revision,
            reported_revision=profile.source_revision,
        )
        if self.capability_resolver is None:
            return profile
        return self._apply_subject_capabilities(profile)

    def with_capability_resolver(
        self,
        resolver: Callable[[str, str], Any],
    ) -> "BoundMonitoringProjectAdapter":
        return replace(self, capability_resolver=resolver)

    def _apply_subject_capabilities(
        self,
        profile: SubjectMonitoringDrilldown,
    ) -> SubjectMonitoringDrilldown:
        states: dict[str, str] = {}
        limitations: dict[str, list[str]] = {}
        unavailable: set[str] = set()
        for capability_id in (
            "subject_timeline",
            "patient_profile",
            "precise_temporal_rules",
            "lab_ctcae_rules",
            "scale_recalculation",
        ):
            try:
                snapshot = self.capability_resolver(
                    self.project_id,
                    capability_id,
                )
            except MonitoringMappingActivationNotFoundError:
                # Existing source-specific adapters remain available before the
                # first formal mapping is activated. Once an active mapping
                # exists, every requested capability is evaluated below.
                return profile
            except MonitoringMappingCapabilityUnavailableError as exc:
                states[capability_id] = "unavailable"
                limitations[capability_id] = [str(exc)]
                unavailable.add(capability_id)
                continue
            states[capability_id] = str(
                getattr(snapshot, "state", "") or ""
            ).strip()
            limitations[capability_id] = [
                str(item)
                for item in getattr(snapshot, "limitation_codes", ()) or ()
                if str(item).strip()
            ]

        if {"subject_timeline", "patient_profile"}.issubset(unavailable):
            raise MonitoringProjectCapabilityUnavailableError(
                "当前字段映射同时不支持 Subject Timeline 和 Patient Profile，"
                "不能返回空页面伪装为分析成功。"
            )

        updates: dict[str, Any] = {
            "capability_mode": (
                "restricted"
                if unavailable
                or any(state == "limited" for state in states.values())
                else "full"
            ),
            "capability_states": states,
            "capability_limitations": limitations,
        }
        review_focus = list(profile.review_focus)
        if "subject_timeline" in unavailable:
            updates["timeline"] = []
            updates["visit_anchors"] = []
            review_focus.append(
                "Subject Timeline 因当前字段映射质量边界不可运行。"
            )
        elif (
            states.get("subject_timeline") == "limited"
            or "precise_temporal_rules" in unavailable
        ):
            updates["timeline"] = [
                event.model_copy(
                    update={"study_day": None, "end_study_day": None}
                )
                for event in profile.timeline
            ]
            updates["visit_anchors"] = [
                anchor.model_copy(
                    update={
                        "actual_study_day": None,
                        "deviation_days": None,
                    }
                )
                for anchor in profile.visit_anchors
            ]
            review_focus.append(
                "时间线以来源日期受限展示，不执行精确研究日或访视窗判断。"
            )
        if "patient_profile" in unavailable:
            updates["efficacy_trends"] = []
            updates["safety_trends"] = []
            review_focus.append(
                "Patient Profile 因当前字段映射质量边界不可运行。"
            )
        else:
            if "scale_recalculation" in unavailable:
                updates["efficacy_trends"] = [
                    metric.model_copy(
                        update={
                            "points": [
                                point.model_copy(
                                    update={
                                        "standardized_value": None,
                                        "change_from_baseline": None,
                                        "percent_change_from_baseline": None,
                                    }
                                )
                                for point in metric.points
                            ]
                        }
                    )
                    for metric in profile.efficacy_trends
                ]
                review_focus.append(
                    "疗效量表仅保留来源值，不执行量表复算或基于复算值的变化推断。"
                )
            if "lab_ctcae_rules" in unavailable:
                updates["safety_trends"] = [
                    metric.model_copy(
                        update={
                            "points": [
                                point.model_copy(
                                    update={
                                        "ctcae_grade": None,
                                        "ctcae_version": "",
                                    }
                                )
                                for point in metric.points
                            ]
                        }
                    )
                    for metric in profile.safety_trends
                ]
                review_focus.append(
                    "安全性趋势保留来源结果，不自动生成 CTCAE 分级。"
                )
        updates["review_focus"] = review_focus
        return profile.model_copy(update=updates)

    def source_revision(self) -> str:
        return self.service.source_revision()

    def evaluate_subject_risks(self, subject_id: str) -> list[RiskCase]:
        source_revision = self.source_revision()
        risks = self.service.evaluate_subject_risks(self.project_id, subject_id)
        for risk in risks:
            self._assert_project(risk.project_id)
        self._assert_stable_source_revision(source_revision)
        return risks

    def protocol_rule_registry(self) -> Dict[str, list[Dict[str, Any]]]:
        source_revision = self.source_revision()
        registry = self.service.protocol_rule_registry()
        self._assert_stable_source_revision(source_revision)
        return registry

    def risk_profile_revision(self) -> str:
        return self.service.risk_profile_revision()

    def risk_engine_version(self) -> str:
        return self.service.risk_engine_version()

    def risk_resolution_complete(self) -> bool:
        resolver = getattr(self.service, "risk_resolution_complete", None)
        return resolver() is True if callable(resolver) else False

    def resolve_source_fragment(self, locator: str) -> Dict[str, Any]:
        source_revision = self.source_revision()
        fragment = self.service.resolve_source_fragment(locator)
        self._assert_stable_source_revision(source_revision)
        return fragment

    def inbox_subject_ids(self) -> list[str]:
        return list(self.risk_subject_ids or tuple(self.subject_ids()))

    def _assert_project(self, actual_project_id: Any) -> None:
        if actual_project_id != self.project_id:
            raise RuntimeError(
                f"monitoring adapter project mismatch: expected {self.project_id}, got {actual_project_id}"
            )

    def _assert_stable_source_revision(
        self,
        expected_revision: str,
        *,
        reported_revision: Any = None,
    ) -> None:
        current_revision = self.source_revision()
        if current_revision != expected_revision:
            raise RuntimeError("monitoring sources changed while the request was being built")
        if reported_revision is not None and reported_revision != expected_revision:
            raise RuntimeError("monitoring response is not bound to the current source revision")


class MonitoringProjectRegistry:
    def __init__(self) -> None:
        self._services: Dict[str, BoundMonitoringProjectAdapter] = {}

    def register(
        self,
        project_id: str,
        service: MonitoringProjectAdapter,
        *,
        risk_subject_ids: Iterable[str] = (),
    ) -> BoundMonitoringProjectAdapter:
        if project_id in self._services:
            raise ValueError(f"monitoring service already registered: {project_id}")
        binding = BoundMonitoringProjectAdapter(
            project_id=project_id,
            service=service,
            risk_subject_ids=tuple(risk_subject_ids),
        )
        self._services[project_id] = binding
        return binding

    def bind_capability_resolver(
        self,
        resolver: Callable[[str, str], Any],
    ) -> None:
        if not callable(resolver):
            raise TypeError("monitoring capability resolver must be callable")
        self._services = {
            project_id: adapter.with_capability_resolver(resolver)
            for project_id, adapter in self._services.items()
        }

    def get(self, project_id: str) -> BoundMonitoringProjectAdapter:
        try:
            return self._services[project_id]
        except KeyError as exc:
            raise KeyError(f"monitoring service not registered: {project_id}") from exc

    def has(self, project_id: str) -> bool:
        return project_id in self._services

    def as_mapping(self) -> Dict[str, BoundMonitoringProjectAdapter]:
        return dict(self._services)
