"""Provider-independent asynchronous generation and sanitized failure contracts."""

from enum import StrEnum
from typing import Generic, Literal, Protocol, TypeVar, assert_never

from pydantic import ValidationError

from .contract_base import NonNegative
from .contracts import ContractModel, ContractViolation

Output = TypeVar("Output", bound=ContractModel)
Stage = Literal[
    "analyze_context",
    "plan_structure",
    "write_sections",
    "integrate_draft",
    "title_and_review",
    "repair_draft",
    "deliver_result",
]
ModelRole = Literal["fast", "quality"]


class ErrorKind(StrEnum):
    """Stable technical categories; provider exception text is never public."""

    CONNECTION = "connection"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    AUTH = "authentication"
    REQUEST = "invalid_request"
    FORMAT = "format"
    REFUSAL = "refusal"
    INCOMPLETE = "incomplete"
    CONFIGURATION = "configuration"


class TokenUsage(ContractModel):
    """One actual provider response, with unknown counts explicitly absent."""

    model: str
    input_tokens: NonNegative | None
    output_tokens: NonNegative | None
    total_tokens: NonNegative | None


class GenerationUsage(ContractModel):
    """Preserve each attempt so known usage survives a later failed request."""

    attempts: tuple[TokenUsage, ...]

    @property
    def total_tokens(self) -> int | None:
        """Return a total only when every attempt reported its actual usage."""
        counts = tuple(attempt.total_tokens for attempt in self.attempts)
        if not counts or any(count is None for count in counts):
            return None
        return sum(count for count in counts if count is not None)


class GenerationResult(ContractModel, Generic[Output]):
    """Only parsed output and normalized accounting cross the model boundary."""

    output: Output
    usage: GenerationUsage


class GenerationError(Exception):
    """Sanitized failure carrying accounting for all attempted requests."""

    def __init__(
        self,
        kind: ErrorKind,
        usage: GenerationUsage,
        *,
        recovered: ContractModel | None = None,
    ) -> None:
        """Keep provider messages, prompts, and response bodies private."""
        self.kind: ErrorKind = kind
        self.usage: GenerationUsage = usage
        self.recovered: ContractModel | None = recovered
        super().__init__(kind.value)

    @property
    def retryable(self) -> bool:
        """Only transient or structural failures consume another attempt."""
        match self.kind:
            case (
                ErrorKind.CONNECTION
                | ErrorKind.TIMEOUT
                | ErrorKind.RATE_LIMIT
                | ErrorKind.SERVER
                | ErrorKind.FORMAT
            ):
                return True
            case (
                ErrorKind.AUTH
                | ErrorKind.REQUEST
                | ErrorKind.REFUSAL
                | ErrorKind.INCOMPLETE
                | ErrorKind.CONFIGURATION
            ):
                return False
            case _:
                assert_never(self.kind)


class OutputRecovery(Protocol):
    """A stage-owned per-call policy validates and merges partial output."""

    def __call__(self, parsed: ContractModel, payload: ContractModel) -> ContractModel | None:
        """Return only a validated partial DTO bound to the supplied payload."""
        ...


def validate_output(
    parsed: Output,
    payload: ContractModel,
    usage: GenerationUsage,
    recover: OutputRecovery | None,
) -> Output:
    """Recover only complete typed output rejected by contextual validation."""
    try:
        return type(parsed).model_validate(parsed.model_dump(), context={"payload": payload})
    except (ValidationError, ContractViolation):
        recovered: ContractModel | None = None
        if recover is not None:
            try:
                candidate = recover(parsed, payload)
                if candidate is not None:
                    recovered = type(candidate).model_validate(
                        candidate.model_dump(), context={"payload": payload}
                    )
            except (ValidationError, ContractViolation):
                recovered = None
        raise GenerationError(ErrorKind.FORMAT, usage, recovered=recovered) from None


class EssayLLM(Protocol):
    """One logical call owns its entire technical retry budget."""

    async def aclose(self) -> None:
        """Release provider-owned clients at service shutdown."""
        ...

    async def generate(
        self,
        stage: Stage,
        payload: ContractModel,
        output_model: type[Output],
        *,
        recover: OutputRecovery | None = None,
    ) -> GenerationResult[Output]:
        """Generate one validated stage output without exposing provider types."""
        ...


def role_for_stage(stage: Stage) -> ModelRole | None:
    """Delivery is deterministic and must never invoke a provider."""
    match stage:
        case "analyze_context" | "plan_structure":
            return "fast"
        case "write_sections" | "integrate_draft" | "title_and_review" | "repair_draft":
            return "quality"
        case "deliver_result":
            return None
        case _:
            assert_never(stage)


def require_role(stage: Stage, role: ModelRole) -> None:
    """Fail before any network request when a stage uses the wrong role."""
    if role_for_stage(stage) != role:
        raise GenerationError(ErrorKind.CONFIGURATION, GenerationUsage(attempts=()))


def parse_backend(value: str) -> Literal["openai", "fake"]:
    """Explicit backend selection never silently falls back to fake."""
    if value in ("openai", "fake"):
        return "openai" if value == "openai" else "fake"
    raise GenerationError(ErrorKind.CONFIGURATION, GenerationUsage(attempts=()))
