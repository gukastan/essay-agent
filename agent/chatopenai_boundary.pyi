# Narrow langchain-openai 1.7.2 surface; upstream has unresolved generic aliases.
from collections.abc import Sequence
from typing import Literal

from httpx import AsyncClient, Timeout
from langchain_core.messages import BaseMessage
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel, SecretStr

class StructuredInvocation:
    async def ainvoke(
        self,
        messages: Sequence[BaseMessage],
        /,
    ) -> BaseModel | dict[str, BaseModel | Exception | None]: ...

class ChatOpenAI:
    root_client: OpenAI
    root_async_client: AsyncOpenAI
    model_name: str
    max_retries: int | None
    request_timeout: float | Timeout | None
    def __init__(
        self,
        *,
        model: str,
        max_retries: int,
        timeout: float | Timeout = ...,
        api_key: SecretStr | None = ...,
        base_url: str | None = ...,
        http_async_client: AsyncClient | None = ...,
    ) -> None: ...
    def with_structured_output(
        self,
        schema: type[BaseModel],
        *,
        method: Literal["json_schema"],
        strict: Literal[True],
        include_raw: Literal[True],
    ) -> StructuredInvocation: ...
