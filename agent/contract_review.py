"""Public contract_review boundary contracts."""

from typing import Annotated, Literal

from pydantic import Field

from .contract_base import (
    CheckStatus,
    ContractModel,
    EvidenceVersion,
    FactId,
    GapId,
    IssueId,
    NonNegative,
    ParagraphId,
    Personalization,
    Positive,
    QuestionKey,
    QuestionStatus,
    RequirementId,
    SectionId,
    SentenceId,
    StopReason,
    SubtitlePlacement,
    VersionId,
)


class Location(ContractModel):
    """Immutable Location payload."""

    paragraph_id: ParagraphId
    paragraph_number: Positive
    sentence_ids: tuple[SentenceId, ...]
    excerpts: tuple[str, ...]


class Suggestion(ContractModel):
    """Immutable Suggestion payload."""

    section_id: SectionId | None
    area: Literal["subtitle", "body", "whole_answer", "submission"]
    sentence_ids: tuple[SentenceId, ...]
    requirement_ids: tuple[RequirementId, ...]
    issue_ids: tuple[IssueId, ...]
    gap_ids: tuple[GapId, ...]
    question_key: QuestionKey | None
    category: Literal["required_edit", "required_info", "optional"]
    missing_detail: str
    why_it_helps: str
    next_action: str
    example_question: str | None
    question_status: QuestionStatus
    priority: NonNegative
    locations: tuple[Location, ...]


class TitleClaim(ContractModel):
    """Immutable TitleClaim payload."""

    meaning: str
    body_sentence_ids: tuple[SentenceId, ...]
    fact_ids: tuple[FactId, ...]


class TitleCheck(ContractModel):
    """Immutable TitleCheck payload."""

    name: str
    status: CheckStatus
    reason: str


class TitleCandidate(ContractModel):
    """Immutable TitleCandidate payload."""

    id: str
    text: str
    kind: Literal["generated", "fixed", "generic"]
    claims: tuple[TitleClaim, ...]
    checks: tuple[TitleCheck, ...]
    decision: Literal["selected", "rejected"]
    reason: str


class TitleReview(ContractModel):
    """Immutable TitleReview payload."""

    condition: Literal["required", "allowed", "forbidden", "fixed", "uncertain"]
    condition_refs: tuple[str, ...]
    placement: SubtitlePlacement
    reason: str
    focus_summary: str | None
    candidates: tuple[TitleCandidate, ...]
    selected_candidate_id: str | None


class SentenceCheck(ContractModel):
    """Immutable SentenceCheck payload."""

    sentence_id: SentenceId
    fact_ids: tuple[FactId, ...]
    status: Literal["source_supported", "general_valid", "unsupported", "conflicting", "unassessed"]
    reason: str


class RequirementCheck(ContractModel):
    """Immutable RequirementCheck payload."""

    requirement_id: RequirementId
    body_sentence_ids: tuple[SentenceId, ...]
    fact_ids: tuple[FactId, ...]
    status: CheckStatus
    missing_detail: str | None
    reason: str


IssueArea = Literal["subtitle", "body", "structure", "submission"]
IssueAction = Literal[
    "remove",
    "narrow",
    "restore_allowed",
    "rewrite",
    "reorder",
    "shorten",
    "replace_title",
    "suggest",
    "report",
]


class ReviewIssue(ContractModel):
    """Immutable ReviewIssue payload."""

    issue_id: IssueId
    code: Literal[
        "missing_information",
        "unsupported_claim",
        "conflicting_claim",
        "prompt_coverage",
        "subtitle",
        "coherence",
        "style",
        "length",
        "submission_condition",
    ]
    area: IssueArea
    sentence_ids: tuple[SentenceId, ...]
    section_ids: tuple[SectionId, ...]
    requirement_ids: tuple[RequirementId, ...]
    fact_ids: tuple[FactId, ...]
    gap_ids: tuple[GapId, ...]
    excerpt: str | None
    reason: str
    action: IssueAction
    verification: str
    fixable_without_new_info: bool
    status: Literal["open", "resolved"]


class LengthCheck(ContractModel):
    """Immutable LengthCheck payload."""

    version_id: VersionId
    body_chars: NonNegative
    subtitle_chars: NonNegative
    separator_chars: NonNegative
    counted_chars: NonNegative
    max_chars: Positive | None
    includes_subtitle: bool
    status: Literal["within", "over", "unspecified"]
    condition_status: CheckStatus
    notes: tuple[str, ...]


class RepairTarget(ContractModel):
    """Immutable RepairTarget payload."""

    issue_id: IssueId
    area: IssueArea
    sentence_ids: tuple[SentenceId, ...]
    section_ids: tuple[SectionId, ...]
    allowed_fact_ids: tuple[FactId, ...]
    operation: IssueAction
    preserve_requirement_ids: tuple[RequirementId, ...]
    acceptance_check: str


class RepairLogEntry(ContractModel):
    """Immutable RepairLogEntry payload."""

    attempt: Annotated[int, Field(ge=1, le=2, strict=True)]
    base_version_id: VersionId
    proposed_version_id: VersionId | None
    outcome: Literal["pending_review", "accepted", "rejected", "no_change", "failed"]
    target_issue_ids: tuple[IssueId, ...]
    reason: str


class ReviewControl(ContractModel):
    """Immutable ReviewControl payload."""

    stop: bool
    reason: StopReason | None


class Quality(ContractModel):
    """Immutable Quality payload."""

    specificity: Literal["adequate", "limited"]
    prompt_coverage: Literal["adequate", "limited"]
    coherence: Literal["adequate", "limited"]


class Review(ContractModel):
    """Immutable Review payload."""

    version_id: VersionId
    evidence_version: EvidenceVersion
    personalization: Personalization
    title_review: TitleReview
    sentence_checks: tuple[SentenceCheck, ...]
    requirement_checks: tuple[RequirementCheck, ...]
    issues: tuple[ReviewIssue, ...]
    length_check: LengthCheck
    quality: Quality
    repair_targets: tuple[RepairTarget, ...]
    fixable_without_new_info: bool
    suggestions: tuple[Suggestion, ...]
    review_status: Literal["performed", "partial", "unavailable"]
