"""Typed graph state shared by nodes without runtime import cycles."""

from typing import TypedDict

from .contracts import (
    Analysis,
    DraftBundle,
    EssayRequest,
    EvidenceVersion,
    Fact,
    IntegrationReport,
    Outline,
    RevisionContext,
    SectionDraft,
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
    candidate_bundle: DraftBundle
    integration_report: IntegrationReport
    usage: tuple[GenerationUsage, ...]
    technical_issues: tuple[TechnicalIssue, ...]


class EssayState(EssayInput, EssayUpdate):
    """Required run seed plus fields accumulated by the ordered stages."""
