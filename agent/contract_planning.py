"""Public contract_planning boundary contracts."""

from typing import Literal, Self

from pydantic import model_validator

from .contract_analysis import HeldClaim
from .contract_base import (
    CandidateId,
    ContractModel,
    EvidenceVersion,
    ExperienceId,
    FactId,
    GapId,
    NonNegative,
    ParagraphId,
    RequirementId,
    SectionId,
    require,
)


class SelectionDecision(ContractModel):
    """Immutable SelectionDecision payload."""

    candidate_id: CandidateId
    decision: Literal["selected", "not_selected", "held"]
    requirement_ids: tuple[RequirementId, ...]
    reason: str
    limits: tuple[str, ...]


class RequirementMap(ContractModel):
    """Immutable RequirementMap payload."""

    requirement_id: RequirementId
    section_ids: tuple[SectionId, ...]
    planned_coverage: Literal["planned_supported", "planned_partial", "unfilled", "not_applicable"]
    gap_ids: tuple[GapId, ...]
    reason: str


class SectionPlan(ContractModel):
    """Immutable SectionPlan payload."""

    section_id: SectionId
    requirement_ids: tuple[RequirementId, ...]
    role: str
    purpose: str
    intended_content: str
    allowed_content: str
    fact_ids: tuple[FactId, ...]
    experience_ids: tuple[ExperienceId, ...]
    gap_ids: tuple[GapId, ...]
    missing_info: tuple[str, ...]
    write_mode: Literal["grounded", "general", "omit"]

    @model_validator(mode="after")
    def omitted_content(self) -> Self:
        """Enforce omitted content boundary semantics."""
        require(
            self.write_mode != "omit" or not self.allowed_content.strip(),
            "omit_content",
            "Omitted sections cannot instruct generated content",
        )
        return self


class ParagraphAllocation(ContractModel):
    """Immutable ParagraphAllocation payload."""

    section_id: SectionId
    content_focus: str
    fact_ids: tuple[FactId, ...]


class PreviousRelation(ContractModel):
    """Immutable PreviousRelation payload."""

    type: Literal["summary", "context", "time", "evidence", "comparison", "causal"]
    reason: str
    fact_ids: tuple[FactId, ...]


class ParagraphPlan(ContractModel):
    """Immutable ParagraphPlan payload."""

    paragraph_id: ParagraphId
    order: NonNegative
    purpose: str
    allocations: tuple[ParagraphAllocation, ...]
    previous_relation: PreviousRelation | None
    weight: NonNegative
    target_chars: NonNegative | None
    budget_reason: str


class SubtitlePlan(ContractModel):
    """Immutable SubtitlePlan payload."""

    purpose: str
    fact_ids: tuple[FactId, ...]
    held_claims: tuple[HeldClaim, ...]


class Budget(ContractModel):
    """Immutable Budget payload."""

    max_chars: NonNegative | None
    subtitle_reserved_chars: NonNegative | None
    separator_chars: NonNegative
    usable_body_chars: NonNegative | None
    constraint_notes: tuple[str, ...]

    @model_validator(mode="after")
    def reservation_matches_limit(self) -> Self:
        """Reserve subtitle characters only when an explicit limit exists."""
        if self.max_chars is None:
            require(
                self.subtitle_reserved_chars is None,
                "unknown_budget",
                "Unknown limits keep subtitle reservations null",
            )
        else:
            require(
                self.subtitle_reserved_chars is not None,
                "known_budget",
                "Known limits require a numeric subtitle reservation",
            )
        return self


class Outline(ContractModel):
    """Immutable Outline payload."""

    evidence_version: EvidenceVersion
    selected_candidate_ids: tuple[CandidateId, ...]
    selected_experience_ids: tuple[ExperienceId, ...]
    selection_decisions: tuple[SelectionDecision, ...]
    core_answer: str | None
    core_answer_fact_ids: tuple[FactId, ...]
    general_direction: str | None
    composition: str
    composition_reason: str
    requirement_map: tuple[RequirementMap, ...]
    sections: tuple[SectionPlan, ...]
    paragraphs: tuple[ParagraphPlan, ...]
    subtitle_plan: SubtitlePlan
    budget: Budget
    design_status: Literal["ready", "partial", "general"]
    planning_notes: tuple[str, ...]
    held_claims: tuple[HeldClaim, ...]
