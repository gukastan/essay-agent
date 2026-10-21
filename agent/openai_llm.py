"""ChatOpenAI-only provider boundary with private raw responses and bounded retries."""

import warnings
from http import HTTPStatus
from json import JSONDecodeError
from typing import ClassVar, Generic

import anyio
from httpx import Timeout
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
)
from pydantic import BaseModel, ConfigDict, PydanticInvalidForJsonSchema, ValidationError

from .chatopenai_boundary import ChatOpenAI
from .contracts import ContractModel, ContractViolation
from .essay_llm import (
    ErrorKind,
    GenerationError,
    GenerationResult,
    GenerationUsage,
    ModelRole,
    Output,
    Stage,
    TokenUsage,
    require_role,
)
from .essay_prompts import build_prompt
from .provider_usage import failed_response_usage
from .retry import with_retry


class _StructuredResponse(BaseModel, Generic[Output]):
    """Parse the LangChain envelope once; it never escapes this module."""

    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True)
    raw: AIMessage
    parsed: Output | None
    parsing_error: Exception | None


class OpenAILLM:
    """Reuse one configured ChatOpenAI client across logical stage calls."""

    def __init__(self, role: ModelRole, client: ChatOpenAI) -> None:
        """Require injected clients to honor the single application retry owner."""
        if client.max_retries != 0:
            raise GenerationError(ErrorKind.CONFIGURATION, GenerationUsage(attempts=()))
        self.role: ModelRole = role
        self.client: ChatOpenAI = client

    async def aclose(self) -> None:
        """Close both public SDK clients even if async cleanup is interrupted."""
        with anyio.CancelScope(shield=True):
            try:
                await self.client.root_async_client.close()
            finally:
                self.client.root_client.close()

    async def generate(
        self,
        stage: Stage,
        payload: ContractModel,
        output_model: type[Output],
    ) -> GenerationResult[Output]:
        """Keep native async invocation, SDK errors, and raw messages inside the adapter."""
        require_role(stage, self.role)
        prompt = build_prompt(stage, payload)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "error",
                    message=".*Overriding to method=.*function_calling.*",
                    category=UserWarning,
                )
                runnable = self.client.with_structured_output(
                    output_model,
                    method="json_schema",
                    strict=True,
                    include_raw=True,
                )
        except (
            ValueError,
            TypeError,
            NotImplementedError,
            UserWarning,
            PydanticInvalidForJsonSchema,
        ):
            raise GenerationError(ErrorKind.REQUEST, GenerationUsage(attempts=())) from None
        messages = [SystemMessage(prompt.system), HumanMessage(prompt.user)]

        async def attempt() -> GenerationResult[Output]:
            usage = GenerationUsage(
                attempts=(
                    TokenUsage(
                        model=self.client.model_name,
                        input_tokens=None,
                        output_tokens=None,
                        total_tokens=None,
                    ),
                )
            )
            try:
                result = await runnable.ainvoke(messages)
                envelope = _StructuredResponse[output_model].model_validate(result)
                usage = _message_usage(envelope.raw, self.client.model_name)
                output = output_model.model_validate(
                    _require_complete(envelope, usage).model_dump(),
                    context={"payload": payload},
                )
            except APITimeoutError:
                raise GenerationError(ErrorKind.TIMEOUT, usage) from None
            except APIConnectionError:
                raise GenerationError(ErrorKind.CONNECTION, usage) from None
            except APIStatusError as error:
                raise GenerationError(
                    _status_kind(error.status_code),
                    failed_response_usage(error, usage),
                ) from None
            except LengthFinishReasonError as error:
                actual = error.completion.usage
                if actual is not None:
                    usage = GenerationUsage(
                        attempts=(
                            TokenUsage(
                                model=error.completion.model,
                                input_tokens=actual.prompt_tokens,
                                output_tokens=actual.completion_tokens,
                                total_tokens=actual.total_tokens,
                            ),
                        )
                    )
                raise GenerationError(ErrorKind.INCOMPLETE, usage) from None
            except ContentFilterFinishReasonError as error:
                raise GenerationError(
                    ErrorKind.REFUSAL,
                    failed_response_usage(error, usage),
                ) from None
            except (ValidationError, JSONDecodeError, ContractViolation) as error:
                raise GenerationError(
                    ErrorKind.FORMAT,
                    failed_response_usage(error, usage),
                ) from None
            return GenerationResult(output=output, usage=usage)

        return await with_retry(attempt)


def _message_usage(message: AIMessage, model: str) -> GenerationUsage:
    """Read standardized AIMessage usage without estimating or pricing tokens."""
    actual = message.usage_metadata
    return GenerationUsage(
        attempts=(
            TokenUsage(
                model=model,
                input_tokens=None if actual is None else actual["input_tokens"],
                output_tokens=None if actual is None else actual["output_tokens"],
                total_tokens=None if actual is None else actual["total_tokens"],
            ),
        )
    )


def _status_kind(status: int) -> ErrorKind:
    """Normalize HTTP status categories without retaining the response body."""
    if status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
        return ErrorKind.AUTH
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        return ErrorKind.RATE_LIMIT
    if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        return ErrorKind.SERVER
    return ErrorKind.REQUEST


class OpenAIFastLLM(OpenAILLM):
    """Analysis and structure provider, constructed once by service lifespan."""

    def __init__(self, model: str) -> None:
        """Let ChatOpenAI resolve credentials; never select a fallback backend."""
        super().__init__("fast", ChatOpenAI(model=model, max_retries=0, timeout=Timeout(120)))


class OpenAIQualityLLM(OpenAILLM):
    """Writing, integration, title/review, and repair provider."""

    def __init__(self, model: str) -> None:
        """Use the same provider parameters without model-specific defaults."""
        super().__init__("quality", ChatOpenAI(model=model, max_retries=0, timeout=Timeout(120)))


def _require_complete(
    envelope: _StructuredResponse[Output],
    usage: GenerationUsage,
) -> Output:
    """Refusal and incomplete termination outrank format failures."""
    if envelope.raw.additional_kwargs.get("refusal"):
        raise GenerationError(ErrorKind.REFUSAL, usage)
    if envelope.raw.response_metadata.get("finish_reason") == "content_filter":
        raise GenerationError(ErrorKind.REFUSAL, usage)
    if envelope.raw.response_metadata.get("finish_reason") == "length":
        raise GenerationError(ErrorKind.INCOMPLETE, usage)
    if envelope.parsing_error is not None or envelope.parsed is None:
        raise GenerationError(ErrorKind.FORMAT, usage)
    return envelope.parsed
