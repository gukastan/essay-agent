"""Typed persisted runs and storage outcomes, independent of HTTP transport."""

from enum import StrEnum
from typing import Literal, Self, assert_never

from pydantic import model_validator

from .contract_base import require
from .contracts import (
    ContractModel,
    EssayRequest,
    EssayResult,
    EvidenceVersion,
    RevisionContext,
    RunErrorPayload,
)

RunStatus = Literal["running", "completed", "failed", "interrupted"]


class StoreUnavailableError(Exception):
    """A sanitized database boundary failure, never an empty successful lookup."""


class StoreConflictError(Exception):
    """A deterministic identity, lineage, or immutable-write conflict."""

    def __init__(self, code: str) -> None:
        """Expose a stable code without SQL or private source text."""
        self.code: str = code
        super().__init__(code)


class RunRecord(ContractModel):
    """Full immutable input and version data read from one persisted run row."""

    request_hash: str
    status: RunStatus
    input: EssayRequest
    evidence_version: EvidenceVersion
    revision_context: RevisionContext
    result: EssayResult | None
    error: RunErrorPayload | None
    created_at: str
    updated_at: str

    @model_validator(mode="after")
    def consistent(self) -> Self:
        """Reject malformed persisted rows rather than reporting false completion."""
        require(
            (self.status == "completed") == (self.result is not None),
            "store_result",
            "Invalid result state",
        )
        require(
            (self.status in ("failed", "interrupted")) == (self.error is not None),
            "store_error",
            "Invalid error state",
        )
        if self.result is not None:
            require(
                self.result.request_id == self.input.request_id
                and self.result.document_id == self.input.document_id
                and self.result.evidence_version == self.evidence_version,
                "store_identity",
                "Result identity differs from reservation",
            )
        if self.error is not None:
            require(
                self.error.request_id == self.input.request_id,
                "store_error_identity",
                "Error identity differs",
            )
        return self


class ReservationKind(StrEnum):
    """Every duplicate is observed without starting another generation."""

    NEW = "new"
    REPLAY = "replay"
    RUNNING = "running"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class Reservation(ContractModel):
    """Admission result; only NEW authorizes a worker to start."""

    kind: ReservationKind
    record: RunRecord


class NormalizedInput(ContractModel):
    """Current user input and server-owned revision history before reservation."""

    request: EssayRequest
    revision_context: RevisionContext


def duplicate_kind(record: RunRecord) -> ReservationKind:
    """Map persisted terminal and active states without authorizing a restart."""
    match record.status:
        case "completed":
            return ReservationKind.REPLAY
        case "running":
            return ReservationKind.RUNNING
        case "failed":
            return ReservationKind.FAILED
        case "interrupted":
            return ReservationKind.INTERRUPTED
        case _:
            assert_never(record.status)


def validate_revision_update(before: RevisionContext, after: RevisionContext) -> None:
    """Allow final status changes while preserving existing question identity and history."""
    if before.source_history != after.source_history:
        code = "source_history_immutable"
        raise StoreConflictError(code)
    updated = {entry.question_key: entry for entry in after.question_registry}
    if len(updated) != len(after.question_registry):
        code = "duplicate_question_key"
        raise StoreConflictError(code)
    for entry in before.question_registry:
        current = updated.get(entry.question_key)
        if (
            current is None
            or current.subject_source_ids != entry.subject_source_ids
            or current.user_response_source_id != entry.user_response_source_id
            or current.missing_detail != entry.missing_detail
        ):
            code = "question_history_immutable"
            raise StoreConflictError(code)


def result_matches(stored: EssayResult | None, generated: EssayResult) -> bool:
    """Compare every serialized field across equivalent runtime model subclasses."""
    return stored is not None and stored.model_dump(mode="json") == generated.model_dump(
        mode="json"
    )
