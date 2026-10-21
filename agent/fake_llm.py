"""Explicit deterministic test adapter; response policies receive only current input."""

from typing import Protocol

from pydantic import ValidationError

from .contracts import ContractModel, ContractViolation
from .essay_llm import (
    ErrorKind,
    GenerationError,
    GenerationResult,
    GenerationUsage,
    ModelRole,
    Output,
    OutputRecovery,
    Stage,
    TokenUsage,
    require_role,
    validate_output,
)
from .retry import with_retry


class FakeResponseFactory(Protocol):
    """Inject stage fixtures or deterministic domain rules, never stored personal stories."""

    def __call__(
        self,
        stage: Stage,
        payload: ContractModel,
        output_model: type[Output],
    ) -> Output:
        """Produce a fresh typed response from the supplied request snapshot."""
        ...


class FakeLLM:
    """A caller-owned response factory makes fake behavior explicit and testable."""

    def __init__(self, role: ModelRole, response_factory: FakeResponseFactory) -> None:
        """Keep no history or hidden sample facts between requests."""
        self.role: ModelRole = role
        self.response_factory: FakeResponseFactory = response_factory

    async def aclose(self) -> None:
        """Match the provider lifecycle; fake owns no external resources."""

    async def generate(
        self,
        stage: Stage,
        payload: ContractModel,
        output_model: type[Output],
        *,
        recover: OutputRecovery | None = None,
    ) -> GenerationResult[Output]:
        """Use the same output contract and retry owner as the live adapter."""
        require_role(stage, self.role)

        async def attempt() -> GenerationResult[Output]:
            usage = GenerationUsage(
                attempts=(
                    TokenUsage(
                        model=f"fake:{self.role}",
                        input_tokens=None,
                        output_tokens=None,
                        total_tokens=None,
                    ),
                )
            )
            try:
                supplied = output_model.model_validate(
                    self.response_factory(stage, payload, output_model).model_dump()
                )
                output = validate_output(supplied, payload, usage, recover)
            except (ValidationError, ContractViolation):
                raise GenerationError(ErrorKind.FORMAT, usage) from None
            return GenerationResult(output=output, usage=usage)

        return await with_retry(attempt)


class FastLLM(FakeLLM):
    """Analysis and structure test adapter."""

    def __init__(self, response_factory: FakeResponseFactory) -> None:
        """Bind the fast role to an explicit response policy."""
        super().__init__("fast", response_factory)


class QualityLLM(FakeLLM):
    """Writing, integration, title/review, and repair test adapter."""

    def __init__(self, response_factory: FakeResponseFactory) -> None:
        """Bind the quality role to an explicit response policy."""
        super().__init__("quality", response_factory)
