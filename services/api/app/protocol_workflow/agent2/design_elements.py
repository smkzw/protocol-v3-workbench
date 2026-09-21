"""Typed design-element proposals: endpoints, estimand, sample size, NI, interim.

One producer pass proposes the remaining high-risk design decisions from the
confirmed study facts and pinned source material, keeping them mutually
consistent by construction. Applicability follows the confirmed design facts:
a superiority design must not propose an NI margin, a design without interim
analysis must not propose alpha spending. Unknown design facts leave the
conditional sections as questions — never silently absent, never assumed
false. Nothing here adopts facts; the caller confirms through the existing
application/CAS command with per-card medical dependencies.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from packages.contracts.workbench_contracts.protocol_v3 import NonEmptyText, SourceArtifact

DESIGN_INSTRUCTION = '''你负责提出研究设计要素建议（目标/终点/估计目标/样本量/条件性设计参数），输出JSON，不批准研究事实。
输入是已确认的研究基础事实与已整理研究资料。所有建议必须与已确认事实一致；资料只供参考引用，不得当作本研究已确认事实。
每节给推荐、备选与理由预填；真实缺口放入questions，禁止用待确认占位词填满字段。
status规则：questions、unresolved_questions或任一节的questions非空时，status必须为needs_information；仅当全部缺口已解决或已在输入中给出时才为ready_for_review。
questions仅用于缺失的输入信息（不知道该填什么）。输入已给出明确值时，即使标注为建议值，也按recommendation采纳（basis='recommendation'）并进入ready_for_review；最终确认由下游逐卡人审完成，不得把"需研究者确认"本身写成question。
适用性由已确认设计事实决定：确证性优效设计不得提出非劣效界值；确认无期中分析时不得提出alpha分配；设计事实未知时对应节保持null并写明需要什么才能决定。
样本量建议必须给出可复算的输入（假设、alpha、power、模型、失访率）与依据，不得只给一个数字。
非劣效界值必须说明临床可接受的最大疗效损失及依据来源。期中分析必须说明信息分数、目的、决策规则与对最终分析的影响。
每条建议标注支持它的来源（source_artifact_id/locator/quote）或标recommendation（含适用前提）。只输出JSON对象。'''


class _DesignShape(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DesignReference(_DesignShape):
    model_config = ConfigDict(extra="forbid")

    source_artifact_id: NonEmptyText
    locator: NonEmptyText
    quote: NonEmptyText


class DesignOption(_DesignShape):
    text: NonEmptyText
    basis: Literal['user', 'source', 'recommendation']
    reason: NonEmptyText
    references: list[DesignReference] = []


class ObjectivesSection(_DesignShape):
    primary: list[DesignOption] = Field(min_length=1)
    secondary: list[DesignOption] = []
    questions: list[NonEmptyText] = []


class EndpointSection(_DesignShape):
    primary_endpoint: DesignOption
    key_secondary: list[DesignOption] = []
    measurement_details: NonEmptyText | None = None
    questions: list[NonEmptyText] = []


class EstimandSection(_DesignShape):
    treatment: DesignOption
    population: DesignOption
    variable: DesignOption
    ice_strategy: DesignOption
    ice_events: list[NonEmptyText] = []
    summary_measure: DesignOption
    questions: list[NonEmptyText] = []


class SampleSizeSection(_DesignShape):
    assumptions: list[NonEmptyText] = Field(min_length=1)
    alpha: NonEmptyText
    power: NonEmptyText
    model: NonEmptyText
    planned_n: NonEmptyText
    attrition: NonEmptyText
    justification: NonEmptyText
    references: list[DesignReference] = []
    questions: list[NonEmptyText] = []


class NonInferioritySection(_DesignShape):
    margin: NonEmptyText
    clinical_justification: NonEmptyText
    references: list[DesignReference] = []
    questions: list[NonEmptyText] = []


class InterimSection(_DesignShape):
    timing: NonEmptyText
    information_fraction: NonEmptyText
    purpose: NonEmptyText
    decision_rule: NonEmptyText
    decision_responsibility: NonEmptyText
    final_analysis_impact: NonEmptyText
    alpha_spending: NonEmptyText | None = None
    questions: list[NonEmptyText] = []


class DesignElementsProposal(_DesignShape):
    status: Literal['ready_for_review', 'needs_information']
    objectives: ObjectivesSection
    endpoint: EndpointSection
    estimand: EstimandSection
    sample_size: SampleSizeSection
    # Conditional sections follow confirmed design facts: null means the
    # confirmed design makes them inapplicable or the facts are not yet known
    # (see questions); a proposal may never invent them for a superiority or
    # interim-free design.
    non_inferiority_margin: NonInferioritySection | None = None
    interim_planning: InterimSection | None = None
    questions: list[NonEmptyText] = []
    unresolved_questions: Annotated[tuple[NonEmptyText, ...], Field(min_length=0)] = ()

    @model_validator(mode='after')
    def check_status(self):
        if self.status == 'ready_for_review' and (self.questions or self.unresolved_questions
                or self.objectives.questions or self.endpoint.questions
                or self.estimand.questions or self.sample_size.questions):
            raise ValueError('design_elements_information_unresolved')
        if self.status == 'needs_information' and not (
                self.questions or self.unresolved_questions
                or self.objectives.questions or self.endpoint.questions
                or self.estimand.questions or self.sample_size.questions):
            raise ValueError('design_elements_needs_information_empty')
        return self


def check_applicable_design(confirmed_facts, proposal: dict) -> None:
    """Conditional sections must agree with the confirmed design facts.

    Unknown interim/NI facts do not make the sections inapplicable; they stay
    questions. Only an explicit confirmed fact forces the agreement.
    """
    status = proposal.get('status')
    ni = proposal.get('non_inferiority_margin')
    interim = proposal.get('interim_planning')
    design = confirmed_facts.get('framing.structured_design')
    design = design if isinstance(design, dict) else {}
    ni_fact = confirmed_facts.get('design.noninferiority_applicable')
    if ni_fact is None:
        ni_fact = design.get('noninferiority_margin_decision')
    interim_fact = confirmed_facts.get('statistics.sample_size.interim_applicable')
    if interim_fact is None:
        interim_fact = design.get('interim_analysis')
    if status == 'ready_for_review':
        ni_denied = ni_fact is False or (
            isinstance(ni_fact, str) and ni_fact.strip().lower() in ('false', '不适用', '无'))
        if ni_denied and ni is not None:
            raise ValueError('design_elements_ni_conflicts_confirmed_design')
        if interim_fact is False and interim is not None:
            raise ValueError('design_elements_interim_conflicts_confirmed_design')
        if ni is None and (ni_fact is True or isinstance(ni_fact, dict)):
            raise ValueError('design_elements_ni_missing_for_confirmed_ni_design')
        if interim is None and interim_fact is True:
            raise ValueError('design_elements_interim_missing_for_confirmed_interim_design')


def read_design_elements_response(prepared, payload):
    """Validate a producer response into a proposal dict; raise on structure."""
    if not isinstance(payload, dict):
        raise ValueError('design_elements_invalid_payload')
    proposal = DesignElementsProposal.model_validate(payload).model_dump(mode='json')
    check_applicable_design(prepared.to_payload().get('confirmed_facts') or {}, proposal)
    proposal['input_sha256'] = prepared.input_sha256
    return {'status': proposal['status'], 'proposal': proposal, 'questions': proposal.get('questions', [])}
