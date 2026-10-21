"""Shared immutable contract primitives."""

from typing import Annotated, ClassVar, Literal, NewType

from pydantic import BaseModel, ConfigDict, Field

SourceId = NewType("SourceId", str)
FactId = NewType("FactId", str)
ExperienceId = NewType("ExperienceId", str)
CandidateId = NewType("CandidateId", str)
RequirementId = NewType("RequirementId", str)
GapId = NewType("GapId", str)
SectionId = NewType("SectionId", str)
ParagraphId = NewType("ParagraphId", str)
SentenceId = NewType("SentenceId", str)
VersionId = NewType("VersionId", str)
EvidenceVersion = NewType("EvidenceVersion", str)
QuestionKey = NewType("QuestionKey", str)
IssueId = NewType("IssueId", str)
NonNegative = Annotated[int, Field(ge=0, strict=True)]
Positive = Annotated[int, Field(gt=0, strict=True)]
SourceKind = Literal["applicant", "company", "job_posting"]
ClaimKind = Literal[
    "personal_event",
    "stated_view",
    "external_context",
    "interpretation",
    "general_statement",
    "connective",
]
InformationRole = Literal["direct", "logical_core", "supporting", "exclude"]
InformationState = Literal["available", "unverified", "conflicting"]
QuestionStatus = Literal["proposed", "asked", "resolved", "unavailable", "not_needed"]
Personalization = Literal["grounded_in_user_input", "partial", "non_personalized"]
CheckStatus = Literal["met", "partial", "unmet", "unassessed", "not_applicable"]
SubtitlePlacement = Literal["answer", "display_only"]
StopReason = Literal[
    "no_fixable_issue",
    "missing_info_only",
    "repair_limit",
    "no_improvement",
    "fallback_after_error",
]


class ContractModel(BaseModel):
    """Closed JSON objects with deeply immutable typed collections."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class ContractViolationError(ValueError):
    """A deterministic boundary contract failed."""

    def __init__(self, code: str, detail: str) -> None:
        """Enforce init boundary semantics."""
        self.code: str = code
        self.detail: str = detail
        super().__init__(f"{code}: {detail}")


def require(condition: bool, code: str, detail: str) -> None:
    """Reject invalid boundary data without asserting semantic truth."""
    if not condition:
        raise ContractViolationError(code, detail)


ContractViolation = ContractViolationError
