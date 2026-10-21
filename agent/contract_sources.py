"""User inputs, preserved source snapshots, and revision lineage."""

from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from .contract_base import (
    ClaimKind,
    ContractModel,
    EvidenceVersion,
    ExperienceId,
    FactId,
    InformationState,
    NonNegative,
    Positive,
    QuestionKey,
    QuestionStatus,
    SourceId,
    SourceKind,
    VersionId,
    require,
)


class StrictLengthPolicy(ContractModel):
    """Immutable StrictLengthPolicy payload."""

    max_chars: Positive | None
    include_spaces: bool
    include_newlines: bool
    include_subtitle: bool


class LengthPolicy(StrictLengthPolicy):
    """Immutable LengthPolicy payload."""

    max_chars: Positive | None = None
    include_spaces: bool = True
    include_newlines: bool = True
    include_subtitle: bool = False


class UserSource(ContractModel):
    """Immutable UserSource payload."""

    source_id: SourceId
    text: str


class QuestionUpdate(ContractModel):
    """Immutable QuestionUpdate payload."""

    question_key: QuestionKey
    response_kind: Literal["answer", "unavailable", "not_needed"]
    text: str | None

    @model_validator(mode="after")
    def check_answer(self) -> Self:
        """Enforce check answer boundary semantics."""
        require(
            (self.response_kind == "answer") == bool(self.text and self.text.strip()),
            "question_response",
            "Only answer responses contain nonempty text",
        )
        return self


class EssayRequest(ContractModel):
    """Immutable EssayRequest payload."""

    request_id: UUID = Field(default_factory=uuid4)
    thread_id: UUID = Field(default_factory=uuid4)
    document_id: UUID = Field(default_factory=uuid4)
    parent_version_id: VersionId | None = None
    company_name: str | None = None
    job_title: str | None = None
    question: str | None = None
    experiences: tuple[UserSource, ...] = ()
    user_views: tuple[UserSource, ...] = ()
    job_posting_text: str | None = None
    company_sources: tuple[UserSource, ...] = ()
    tone: str = "담백한 존댓말"
    length_policy: LengthPolicy = Field(default_factory=LengthPolicy)
    revision_instruction: str | None = None
    question_updates: tuple[QuestionUpdate, ...] = ()


class CatalogSourceMetadata(ContractModel):
    """Original immutable catalog attribution preserved with MCP evidence."""

    source_id: str
    company: str
    job_title: str | None
    relative_path: str
    registered_at: str
    published_at: str | None


class SourceMetadata(ContractModel):
    """Immutable SourceMetadata payload."""

    origin: Literal["user", "mcp"]
    label: str | None
    uri: str | None
    catalog: CatalogSourceMetadata | None


class SourceSnapshot(ContractModel):
    """Immutable SourceSnapshot payload."""

    source_id: SourceId
    evidence_version: EvidenceVersion
    source_kind: SourceKind
    text: str
    metadata: SourceMetadata
    source_order: NonNegative

    @model_validator(mode="after")
    def applicant_origin(self) -> Self:
        """Enforce applicant origin boundary semantics."""
        require(
            self.source_kind != "applicant" or self.metadata.origin == "user",
            "source_origin",
            "Applicant evidence must be user supplied",
        )
        return self


class SourceSpan(ContractModel):
    """Immutable SourceSpan payload."""

    start: NonNegative
    end: Positive

    @model_validator(mode="after")
    def ordered(self) -> Self:
        """Enforce ordered boundary semantics."""
        require(self.end > self.start, "source_span", "Span end must follow start")
        return self


class Fact(ContractModel):
    """Immutable Fact payload."""

    fact_id: FactId
    source_id: SourceId
    source_kind: SourceKind
    quote: str
    span: SourceSpan
    experience_id: ExperienceId | None
    claim_kind: ClaimKind
    attribution: str
    information_state: InformationState
    conflict_ids: tuple[FactId, ...]


class SourceHistory(ContractModel):
    """Immutable SourceHistory payload."""

    source_id: SourceId
    previous_text: str | None
    current_text: str | None
    status: Literal["active", "superseded", "removed"]
    evidence_version: EvidenceVersion


class QuestionRegistryEntry(ContractModel):
    """Immutable QuestionRegistryEntry payload."""

    question_key: QuestionKey
    subject_source_ids: tuple[SourceId, ...]
    missing_detail: str
    question_status: QuestionStatus
    user_response_source_id: SourceId | None


class RevisionContext(ContractModel):
    """Immutable RevisionContext payload."""

    source_history: tuple[SourceHistory, ...]
    question_registry: tuple[QuestionRegistryEntry, ...]


class StoredParent(ContractModel):
    """Immutable StoredParent payload."""

    document_id: UUID
    version_id: VersionId


def validate_request_parent(request: EssayRequest, parent: StoredParent | None) -> None:
    """Verify lineage against a server-loaded parent, never client metadata."""
    if request.parent_version_id is not None:
        require(parent is not None, "parent_missing", "Stored parent is required")
        if parent is not None:
            require(
                parent.document_id == request.document_id
                and parent.version_id == request.parent_version_id,
                "parent_mismatch",
                "Parent must belong to this document and version",
            )
