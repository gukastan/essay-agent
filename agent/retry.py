"""A single initial-plus-one budget shared by transport and format failures."""

from collections.abc import Awaitable, Callable
from typing import Final

import anyio

from .essay_llm import GenerationError, GenerationResult, GenerationUsage, Output, TokenUsage

MAX_ATTEMPTS: Final = 2


async def with_retry(
    operation: Callable[[], Awaitable[GenerationResult[Output]]],
    *,
    base_delay: float = 0.3,
) -> GenerationResult[Output]:
    """Retry only normalized failures; cancellation always propagates untouched."""
    attempts: tuple[TokenUsage, ...] = ()
    for attempt in range(MAX_ATTEMPTS):
        try:
            result = await operation()
        except GenerationError as error:
            attempts += error.usage.attempts
            if not error.retryable or attempt + 1 == MAX_ATTEMPTS:
                raise GenerationError(error.kind, GenerationUsage(attempts=attempts)) from None
            await anyio.sleep(base_delay)
        else:
            return GenerationResult(
                output=result.output,
                usage=GenerationUsage(attempts=attempts + result.usage.attempts),
            )
    raise AssertionError  # The final failed attempt always raises above.
