"""Integration data contracts independent of validation and node execution."""

from .contracts import (
    ContractModel,
    DraftBundle,
    DraftParagraph,
    IntegrationEdit,
    IntegrationIssue,
    IntegrationRequirementCheck,
    ReverseOutline,
    SectionDraft,
    VersionId,
    WritingReport,
)
from .stage_writing_models import WritingPayload


class IntegrationPayload(WritingPayload):
    """Keep baseline and writing-stage records immutable during editing."""

    section_drafts: tuple[SectionDraft, ...]
    writing_report: WritingReport
    baseline_bundle: DraftBundle
    candidate_version_id: VersionId


class IntegrationProposal(ContractModel):
    """Propose current prose and explicit edit/semantic comparison records."""

    paragraphs: tuple[DraftParagraph, ...]
    edits: tuple[IntegrationEdit, ...]
    reverse_outline: tuple[ReverseOutline, ...]
    requirement_checks: tuple[IntegrationRequirementCheck, ...]
    issues: tuple[IntegrationIssue, ...]
