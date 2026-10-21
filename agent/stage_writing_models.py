"""Typed stage-three payload and complete parsed provider response."""

from typing import Self

from pydantic import model_validator

from .contract_base import Personalization
from .contracts import (
    Analysis,
    ContractContext,
    ContractModel,
    EssayRequest,
    EvidenceVersion,
    Fact,
    Outline,
    SectionCheck,
    SectionDraft,
    SentenceId,
    SourceSnapshot,
    WritingNote,
)
from .stage_analysis_models import PayloadValidationInfo
from .stage_writing_validation import validate_writing_parts


class WritingPayload(ContractModel):
    """Freeze all source, analysis and allocation context for one writing call."""

    request: EssayRequest
    evidence_version: EvidenceVersion
    sources: tuple[SourceSnapshot, ...]
    facts: tuple[Fact, ...]
    analysis: Analysis
    outline: Outline


class WritingOutput(ContractModel):
    """Keep model semantic notes separate from Python versions and measurements."""

    section_drafts: tuple[SectionDraft, ...]
    notes: tuple[WritingNote, ...]
    section_checks: tuple[SectionCheck, ...]
    personalization: Personalization

    @model_validator(mode="after")
    def current_payload(self, info: PayloadValidationInfo) -> Self:
        """Check parsed references within the shared provider retry budget."""
        if info.context is not None:
            payload = WritingPayload.model_validate(info.context["payload"])
            validate_writing_parts(self.section_drafts, writing_context(payload))
        return self


class WritingRecovery(WritingOutput):
    """Server-collected IDs of complete parsed proposals, never provider-supplied history."""

    original_sentence_ids: tuple[SentenceId, ...]


def writing_context(payload: WritingPayload) -> ContractContext:
    """Provide the immutable current-source validation context."""
    return ContractContext(
        evidence_version=payload.evidence_version,
        sources=payload.sources,
        facts=payload.facts,
        analysis=payload.analysis,
        outline=payload.outline,
    )
