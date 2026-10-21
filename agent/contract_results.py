"""Public contract_results boundary contracts."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from .contract_base import (
    CheckStatus,
    ContractModel,
    EvidenceVersion,
    NonNegative,
    Personalization,
    RequirementId,
    SectionId,
    SentenceId,
    SourceKind,
    StopReason,
    SubtitlePlacement,
    VersionId,
)
from .contract_review import LengthCheck, Location, Quality, Suggestion
from .contract_sources import StrictLengthPolicy


class RequirementStatus(ContractModel):
    """Immutable RequirementStatus payload."""

    requirement_id: RequirementId
    status: CheckStatus


class StructureEntry(ContractModel):
    """Immutable StructureEntry payload."""

    section_id: SectionId
    purpose: str
    intended_content: str
    actual_sentence_ids: tuple[SentenceId, ...]
    locations: tuple[Location, ...]
    requirement_ids: tuple[RequirementId, ...]
    requirement_statuses: tuple[RequirementStatus, ...]
    coverage: Literal["supported", "general", "not_expressed", "unassessed"]
    missing_info: tuple[str, ...]


class QualityReport(Quality):
    """Immutable QualityReport payload."""

    review_status: Literal["performed", "partial", "unavailable"]
    display_status: Literal["reviewed_draft", "needs_attention", "review_incomplete"]
    length_check: LengthCheck
    subtitle_reason: str
    required_item_count: NonNegative
    key_guidance: tuple[str, ...]
    unverified_conditions: tuple[str, ...]
    technical_limits: tuple[str, ...]


class SourceSummary(ContractModel):
    """Immutable SourceSummary payload."""

    source_kind: SourceKind
    provided_source_count: NonNegative
    used_fact_count: NonNegative


class EssayResult(ContractModel):
    """Immutable EssayResult payload."""

    document_id: UUID
    request_id: UUID
    version_id: VersionId
    evidence_version: EvidenceVersion
    subtitle: str
    subtitle_placement: SubtitlePlacement
    body: str
    copy_text: str
    character_count: NonNegative
    length_policy: StrictLengthPolicy
    personalization: Personalization
    structure: tuple[StructureEntry, ...]
    suggestions: tuple[Suggestion, ...]
    quality_report: QualityReport
    source_summary: tuple[SourceSummary, ...]
    generation_status: Literal["completed", "completed_with_fallback"]
    stop_reason: StopReason


class RunErrorPayload(ContractModel):
    """Immutable RunErrorPayload payload."""

    request_id: UUID | None
    generation_status: Literal["technical_error"]
    code: str
    message: str
    last_result: EssayResult | None


class TechnicalIssue(ContractModel):
    """Immutable TechnicalIssue payload."""

    node: str
    code: str
    attempts: NonNegative
    exhausted: bool
    recovered: bool
    message: str


PersistenceStatus = Literal["pending", "stored", "failed", "unknown"]


class ResponseMetadata(ContractModel):
    """Immutable ResponseMetadata payload."""

    persistence_status: PersistenceStatus


class StageStarted(ContractModel):
    """Immutable StageStarted payload."""

    event: Literal["StageStarted"]
    request_id: UUID
    stage: Annotated[int, Field(ge=1, le=6, strict=True)]
    repair_count: Annotated[int, Field(ge=0, le=2, strict=True)]


class StageCompleted(ContractModel):
    """Immutable StageCompleted payload."""

    event: Literal["StageCompleted"]
    request_id: UUID
    stage: Annotated[int, Field(ge=1, le=6, strict=True)]
    repair_count: Annotated[int, Field(ge=0, le=2, strict=True)]


class FinalResult(ContractModel):
    """Immutable FinalResult payload."""

    event: Literal["FinalResult"]
    result: EssayResult
    persistence_status: PersistenceStatus


class RunError(ContractModel):
    """Immutable RunError payload."""

    event: Literal["RunError"]
    error: RunErrorPayload


ProgressEvent = Annotated[
    StageStarted | StageCompleted | FinalResult | RunError, Field(discriminator="event")
]
