"""Analysis structured-output boundary and current-source validation."""

from collections.abc import Mapping
from typing import Literal, Protocol, Self

from pydantic import model_validator

from .contract_base import require
from .contracts import (
    Analysis,
    ContractContext,
    ContractModel,
    EssayRequest,
    EvidenceVersion,
    Fact,
    RevisionContext,
    SourceSnapshot,
    validate_contract,
)


class PayloadValidationInfo(Protocol):
    """Typed adapter-supplied context consumed by stage validators."""

    @property
    def context(self) -> Mapping[str, ContractModel] | None:
        """Expose only the typed payload entry supplied by the adapter."""
        ...


class AnalysisPayload(ContractModel):
    """Only active source snapshots can establish personal evidence."""

    request: EssayRequest
    evidence_version: EvidenceVersion
    sources: tuple[SourceSnapshot, ...]
    revision_context: RevisionContext
    research_status: Literal["available", "partial", "unavailable", "not_requested"]


class AnalysisOutput(ContractModel):
    """Source references are checked inside the adapter's shared retry budget."""

    facts: tuple[Fact, ...]
    analysis: Analysis

    @model_validator(mode="after")
    def current_sources(self, info: PayloadValidationInfo) -> Self:
        """SDK parsing has no context; adapter reparsing supplies the current payload."""
        if info.context is None:
            return self
        payload = AnalysisPayload.model_validate(info.context["payload"])
        validate_contract(
            ContractContext(
                evidence_version=payload.evidence_version,
                sources=payload.sources,
                facts=self.facts,
                analysis=self.analysis,
            )
        )
        require(
            bool(self.analysis.requirements), "requirements", "Keep a question or general direction"
        )
        for requirement in self.analysis.requirements:
            if requirement.origin == "explicit":
                require(
                    bool(payload.request.question), "question_origin", "Explicit needs a question"
                )
        return self
