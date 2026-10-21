"""Public HTTP envelopes keep persistence separate from generated essay quality."""

from typing import Literal
from uuid import UUID

from .contract_results import PersistenceStatus
from .contracts import (
    ContractModel,
    EssayRequest,
    EssayResult,
    ResponseMetadata,
    RunErrorPayload,
    VersionId,
)
from .store_models import RunStatus


class ChatResponse(ContractModel):
    """The same EssayResult delivered by JSON, SSE and saved lookup."""

    result: EssayResult
    metadata: ResponseMetadata


class ErrorResponse(ContractModel):
    """One sanitized technical error shape across all transports."""

    error: RunErrorPayload


class RunLookup(ContractModel):
    """Only original form fields are exposed as editable input."""

    request_id: UUID
    status: RunStatus
    result: EssayResult | None
    error: RunErrorPayload | None
    persistence_status: PersistenceStatus
    input: EssayRequest | None


class VersionSummary(ContractModel):
    """Persisted completed version identity for document navigation."""

    request_id: UUID
    version_id: VersionId
    created_at: str
    generation_status: Literal["completed", "completed_with_fallback"]


class VersionList(ContractModel):
    """Completed versions only, ordered by persisted creation time."""

    document_id: UUID
    versions: tuple[VersionSummary, ...]


class HealthResponse(ContractModel):
    """Nonsecret lifecycle identity and backend availability."""

    status: Literal["ok"] = "ok"
    instance_id: UUID
    creation_count: int
    llm_backend: Literal["openai", "fake"]
    fast_model: str
    quality_model: str
    mcp_status: Literal["ready", "unavailable", "disabled"]
    active_runs: int


class ServiceError(Exception):
    """HTTP admission/query failure with a safe shared response body."""

    def __init__(self, status: int, error: RunErrorPayload, location: str | None = None) -> None:
        """Carry no request body, SQL exception or provider diagnostic text."""
        self.status: int = status
        self.error: RunErrorPayload = error
        self.location: str | None = location
        super().__init__(error.code)


def run_error(request_id: UUID | None, code: str, message: str) -> RunErrorPayload:
    """Create a technical outcome without inventing a previous usable result."""
    return RunErrorPayload(
        request_id=request_id,
        generation_status="technical_error",
        code=code,
        message=message,
        last_result=None,
    )
