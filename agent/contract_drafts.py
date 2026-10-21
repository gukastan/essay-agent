"""Public contract_drafts boundary contracts."""

from typing import Literal, Self

from pydantic import model_validator

from .contract_base import (
    ClaimKind,
    ContractModel,
    EvidenceVersion,
    FactId,
    GapId,
    NonNegative,
    ParagraphId,
    Personalization,
    RequirementId,
    SectionId,
    SentenceId,
    SubtitlePlacement,
    VersionId,
    require,
)


class Sentence(ContractModel):
    """Immutable Sentence payload."""

    sentence_id: SentenceId
    text: str
    section_ids: tuple[SectionId, ...]
    claim_kind: ClaimKind
    fact_ids: tuple[FactId, ...]

    @model_validator(mode="after")
    def grounded_claim(self) -> Self:
        """Enforce grounded claim boundary semantics."""
        require(bool(self.text.strip()), "empty_sentence", "Sentence text must be readable")
        require(
            self.claim_kind in ("general_statement", "connective") or bool(self.fact_ids),
            "claim_evidence",
            "A factual claim requires evidence",
        )
        return self


class DraftAllocation(ContractModel):
    """Immutable DraftAllocation payload."""

    planned_paragraph_id: ParagraphId
    sentences: tuple[Sentence, ...]


class SectionDraft(ContractModel):
    """Immutable SectionDraft payload."""

    section_id: SectionId
    allocations: tuple[DraftAllocation, ...]


class DraftParagraph(ContractModel):
    """Immutable DraftParagraph payload."""

    paragraph_id: ParagraphId
    sentences: tuple[Sentence, ...]


class DraftBundle(ContractModel):
    """Immutable DraftBundle payload."""

    version_id: VersionId
    evidence_version: EvidenceVersion
    paragraphs: tuple[DraftParagraph, ...]
    subtitle: str | None
    subtitle_fact_ids: tuple[FactId, ...]
    subtitle_placement: SubtitlePlacement
    personalization: Personalization


class LengthSnapshot(ContractModel):
    """Immutable LengthSnapshot payload."""

    body_chars: NonNegative
    max_chars: NonNegative | None
    include_spaces: bool
    include_newlines: bool
    include_subtitle: bool
    subtitle_pending: bool
    measurement_scope: Literal["body_only"]
    body_limit_status: Literal["within", "over", "unspecified"]

    @model_validator(mode="after")
    def pending_title(self) -> Self:
        """Enforce pending title boundary semantics."""
        require(
            self.subtitle_pending == self.include_subtitle,
            "subtitle_pending",
            "Body-only count awaits included subtitle",
        )
        expected = (
            "unspecified"
            if self.max_chars is None
            else "over"
            if self.body_chars > self.max_chars
            else "within"
        )
        require(
            self.body_limit_status == expected,
            "length_status",
            "Length status must match measured count",
        )
        return self


class WritingNote(ContractModel):
    """Immutable WritingNote payload."""

    code: Literal[
        "missing_information",
        "contract_mismatch",
        "unsupported_claim",
        "conflict",
        "coherence",
        "style",
        "length",
    ]
    section_ids: tuple[SectionId, ...]
    requirement_ids: tuple[RequirementId, ...]
    sentence_ids: tuple[SentenceId, ...]
    gap_ids: tuple[GapId, ...]
    handling: Literal["omitted", "narrowed", "general", "retained_for_review"]
    message: str
    proposed_question: str | None


class SectionCheck(ContractModel):
    """Immutable SectionCheck payload."""

    section_id: SectionId
    state: Literal["drafted", "partial", "not_written", "general"]
    sentence_ids: tuple[SentenceId, ...]
    requirement_ids: tuple[RequirementId, ...]
    gap_ids: tuple[GapId, ...]
    reason: str


class WritingReport(ContractModel):
    """Immutable WritingReport payload."""

    draft_id: VersionId
    evidence_version: EvidenceVersion
    personalization: Personalization
    notes: tuple[WritingNote, ...]
    section_checks: tuple[SectionCheck, ...]
    length_snapshot: LengthSnapshot
    fallback_sentences: tuple[Sentence, ...]


class IntegrationEdit(ContractModel):
    """Immutable IntegrationEdit payload."""

    operation: Literal[
        "retain",
        "move",
        "rewrite",
        "merge",
        "split",
        "delete",
        "add_grounded",
        "add_connective",
        "add_fallback",
    ]
    before_sentence_ids: tuple[SentenceId, ...]
    after_sentence_ids: tuple[SentenceId, ...]
    section_ids: tuple[SectionId, ...]
    fact_ids: tuple[FactId, ...]
    reason: str


class ReverseOutline(ContractModel):
    """Immutable ReverseOutline payload."""

    scope: Literal["baseline", "candidate"]
    paragraph_id: ParagraphId
    sentence_ids: tuple[SentenceId, ...]
    section_ids: tuple[SectionId, ...]
    fact_ids: tuple[FactId, ...]
    gist: str | None
    roles: tuple[str, ...]
    requirement_ids: tuple[RequirementId, ...]
    semantic_status: Literal["assessed", "unassessed"]
    difference_from_plan: str | None


ExpressionState = Literal["expressed", "partial", "not_expressed", "unassessed"]


class IntegrationRequirementCheck(ContractModel):
    """Immutable IntegrationRequirementCheck payload."""

    requirement_id: RequirementId
    baseline_sentence_ids: tuple[SentenceId, ...]
    candidate_sentence_ids: tuple[SentenceId, ...]
    before_state: ExpressionState
    after_state: ExpressionState
    gap_ids: tuple[GapId, ...]
    missing_detail: str | None
    reason: str


class IntegrationIssue(ContractModel):
    """Immutable IntegrationIssue payload."""

    code: str
    scope: Literal["baseline", "rejected_candidate", "current"]
    sentence_ids: tuple[SentenceId, ...]
    section_ids: tuple[SectionId, ...]
    requirement_ids: tuple[RequirementId, ...]
    gap_ids: tuple[GapId, ...]
    status: Literal["open", "resolved"]
    message: str
    handling: str


class IntegrationReport(ContractModel):
    """Immutable IntegrationReport payload."""

    source_draft_id: VersionId
    evidence_version: EvidenceVersion
    baseline_bundle: DraftBundle
    candidate_version_id: VersionId
    selection: Literal["edited", "baseline", "general_fallback"]
    selection_reason: str
    edits: tuple[IntegrationEdit, ...]
    reverse_outline: tuple[ReverseOutline, ...]
    requirement_checks: tuple[IntegrationRequirementCheck, ...]
    length_before: LengthSnapshot
    length_after: LengthSnapshot
    issues: tuple[IntegrationIssue, ...]
