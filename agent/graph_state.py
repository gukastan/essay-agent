"""Typed graph state shared by nodes without runtime import cycles."""

from typing import TypedDict

from .contract_base import StopReason
from .contracts import (
    Analysis,
    DraftBundle,
    EssayRequest,
    EssayResult,
    EvidenceVersion,
    Fact,
    IntegrationReport,
    Outline,
    RepairLogEntry,
    Review,
    ReviewControl,
    RevisionContext,
    SectionDraft,
    Sentence,
    SourceSnapshot,
    TechnicalIssue,
    WritingReport,
)
from .essay_llm import GenerationUsage


class EssayInput(TypedDict):
    """Server-owned seed required before the first node executes."""

    request: EssayRequest
    evidence_version: EvidenceVersion
    revision_context: RevisionContext


class EssayUpdate(TypedDict, total=False):
    """Node-local updates never replace immutable request context."""

    previous_draft: DraftBundle | None
    sources: tuple[SourceSnapshot, ...]
    facts: tuple[Fact, ...]
    analysis: Analysis
    outline: Outline
    section_drafts: tuple[SectionDraft, ...]
    writing_report: WritingReport
    fallback_provenance: tuple[Sentence, ...]
    candidate_bundle: DraftBundle
    integration_report: IntegrationReport
    reviewed_bundle: DraftBundle
    review: Review
    best_bundle: DraftBundle
    best_review: Review
    repair_count: int
    repair_log: tuple[RepairLogEntry, ...]
    review_control: ReviewControl
    stop_reason: StopReason | None
    result: EssayResult
    usage: tuple[GenerationUsage, ...]
    technical_issues: tuple[TechnicalIssue, ...]


class EssayState(EssayInput, EssayUpdate):
    """Required run seed plus fields accumulated by the ordered stages."""
