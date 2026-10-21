"""Analysis outputs retain requirements independently from evidence availability."""

from typing import Literal

from .contract_base import (
    CandidateId,
    ContractModel,
    ExperienceId,
    FactId,
    GapId,
    InformationRole,
    InformationState,
    NonNegative,
    QuestionKey,
    QuestionStatus,
    RequirementId,
)


class Requirement(ContractModel):
    """Immutable Requirement payload."""

    requirement_id: RequirementId
    description: str
    resolution: Literal["interpreted", "unparsed"]
    origin: Literal["explicit", "interpreted"]
    information_role: InformationRole
    required_by_prompt: bool
    application_condition: str | None
    reason: str


class ExperienceCandidate(ContractModel):
    """Immutable ExperienceCandidate payload."""

    experience_id: ExperienceId
    fact_ids: tuple[FactId, ...]
    source_order: NonNegative


class AnswerCandidate(ContractModel):
    """Immutable AnswerCandidate payload."""

    candidate_id: CandidateId
    experience_ids: tuple[ExperienceId, ...]
    fact_ids: tuple[FactId, ...]
    requirement_ids: tuple[RequirementId, ...]
    source_order: NonNegative


class EvidenceLink(ContractModel):
    """Immutable EvidenceLink payload."""

    requirement_id: RequirementId
    candidate_id: CandidateId
    fact_ids: tuple[FactId, ...]
    information_role: InformationRole
    information_state: InformationState
    applicability: Literal["applies", "not_applicable"]
    use_status: Literal["candidate", "held", "excluded"]
    reason: str


class Gap(ContractModel):
    """Immutable Gap payload."""

    gap_id: GapId
    question_key: QuestionKey
    requirement_ids: tuple[RequirementId, ...]
    candidate_id: CandidateId | None
    missing_detail: str
    why_it_matters: str
    priority: NonNegative
    question: str | None
    question_status: QuestionStatus


class HeldClaim(ContractModel):
    """Immutable HeldClaim payload."""

    description: str
    reason: str
    fact_ids: tuple[FactId, ...]
    requirement_ids: tuple[RequirementId, ...]


class ContextClaim(ContractModel):
    """Immutable ContextClaim payload."""

    description: str
    fact_ids: tuple[FactId, ...]
    reason: str


class WritingCondition(ContractModel):
    """Immutable WritingCondition payload."""

    description: str
    origin: Literal["explicit", "interpreted"]
    quote: str | None


class Analysis(ContractModel):
    """Immutable Analysis payload."""

    analysis_status: Literal["complete", "partial", "unavailable"]
    question_type: str
    requirements: tuple[Requirement, ...]
    writing_conditions: tuple[WritingCondition, ...]
    company_role_context: tuple[ContextClaim, ...]
    experience_candidates: tuple[ExperienceCandidate, ...]
    answer_candidates: tuple[AnswerCandidate, ...]
    evidence_links: tuple[EvidenceLink, ...]
    competency_candidates: tuple[ContextClaim, ...]
    role_links: tuple[ContextClaim, ...]
    gaps: tuple[Gap, ...]
    held_claims: tuple[HeldClaim, ...]
    research_status: Literal["available", "partial", "unavailable", "not_requested"]
