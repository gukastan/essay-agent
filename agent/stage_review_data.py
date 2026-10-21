"""Current-payload review and targeted repair provider boundaries."""

from .contracts import (
    ContractModel,
    DraftBundle,
    DraftParagraph,
    FactId,
    IntegrationEdit,
    IntegrationReport,
    Quality,
    RequirementCheck,
    Review,
    ReviewIssue,
    Sentence,
    SentenceCheck,
    Suggestion,
    TitleReview,
    WritingReport,
)
from .stage_writing_models import WritingPayload


class ReviewPayload(WritingPayload):
    """Freeze current draft and historical composition reports for one review."""

    fallback_provenance: tuple[Sentence, ...]
    candidate_bundle: DraftBundle
    writing_report: WritingReport
    integration_report: IntegrationReport
    repair_count: int


class ReviewJudgments(ContractModel):
    """Keep model judgments separate from server routing, identity and measurements."""

    title_review: TitleReview
    sentence_checks: tuple[SentenceCheck, ...]
    requirement_checks: tuple[RequirementCheck, ...]
    issues: tuple[ReviewIssue, ...]
    quality: Quality
    suggestions: tuple[Suggestion, ...]


class RepairPayload(ReviewPayload):
    """Supply the chosen best version and only its current repair targets."""

    review: Review


class RepairProposal(ContractModel):
    """Return changed prose with an exhaustive before/after sentence trace."""

    paragraphs: tuple[DraftParagraph, ...]
    subtitle: str | None
    subtitle_fact_ids: tuple[FactId, ...]
    edits: tuple[IntegrationEdit, ...]
