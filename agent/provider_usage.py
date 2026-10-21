"""Recover accounting from SDK parse failures before LangChain creates a message."""

from typing import ClassVar

from httpx import Response
from pydantic import BaseModel, ConfigDict, ValidationError

from .contract_base import NonNegative
from .essay_llm import GenerationUsage, TokenUsage


class _FailureResponse(BaseModel):
    """LangChain attaches the original HTTP response to SDK parsing exceptions."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        arbitrary_types_allowed=True,
        from_attributes=True,
    )
    response: Response | None = None


class _Usage(BaseModel):
    """Only accounting fields are retained from an otherwise private HTTP body."""

    prompt_tokens: NonNegative | None = None
    completion_tokens: NonNegative | None = None
    total_tokens: NonNegative | None = None


class _Completion(BaseModel):
    """Ignore content and parse only optional provider usage metadata."""

    model: str
    usage: _Usage | None = None


def failed_response_usage(error: Exception, previous: GenerationUsage) -> GenerationUsage:
    """Preserve measured tokens on format/refusal failures without leaking content."""
    try:
        carrier = _FailureResponse.model_validate(error)
        if carrier.response is None:
            return previous
        completion = _Completion.model_validate_json(carrier.response.content)
    except ValidationError:
        return previous
    actual = completion.usage
    if actual is None:
        return previous
    return GenerationUsage(
        attempts=(
            TokenUsage(
                model=completion.model,
                input_tokens=actual.prompt_tokens,
                output_tokens=actual.completion_tokens,
                total_tokens=actual.total_tokens,
            ),
        )
    )
