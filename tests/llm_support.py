"""Real ChatOpenAI transport fixtures with no live credentials or external requests."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal, assert_never

import anyio
import httpx
from pydantic import BaseModel, JsonValue, SecretStr

from agent.chatopenai_boundary import ChatOpenAI
from agent.contracts import ContractModel
from agent.essay_llm import ModelRole, Output, Stage
from agent.openai_llm import OpenAILLM


class SuppliedFacts(ContractModel):
    facts: tuple[str, ...]


class FactOutput(ContractModel):
    facts: tuple[str, ...]
    note: str | None


class EchoFacts:
    def __call__(
        self,
        stage: Stage,
        payload: ContractModel,
        output_model: type[Output],
    ) -> Output:
        source = SuppliedFacts.model_validate(payload.model_dump())
        return output_model.model_validate({"facts": source.facts, "note": None})


class Message(BaseModel):
    role: str
    content: str


class SchemaFormat(BaseModel):
    type: str
    json_schema: dict[str, JsonValue]


class RequestBody(BaseModel):
    model: str
    messages: tuple[Message, ...]
    response_format: SchemaFormat


@dataclass(frozen=True, slots=True)
class Reply:
    body: str = ""
    status: int = 200
    error: Literal["timeout", "connection", "wait"] | None = None


@dataclass(frozen=True, slots=True)
class Harness:
    adapter: OpenAILLM
    requests: list[RequestBody]
    client: ChatOpenAI


def completion(content: str, *, finish: str = "stop", usage: bool = True) -> Reply:
    body = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {"role": "assistant", "content": content, "refusal": None},
            }
        ],
    }
    encoded = json.dumps(body)
    if usage:
        encoded = encoded[:-1] + (
            ', "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}}'
        )
    return Reply(encoded)


@asynccontextmanager
async def provider(
    replies: tuple[Reply, ...],
    role: ModelRole = "fast",
    model: str = "gpt-4o-mini",
) -> AsyncGenerator[Harness]:
    requests: list[RequestBody] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(RequestBody.model_validate_json(request.content))
        reply = replies[len(requests) - 1]
        message = "test transport failure"
        match reply.error:
            case "timeout":
                raise httpx.ReadTimeout(message, request=request)
            case "connection":
                raise httpx.ConnectError(message, request=request)
            case "wait":
                await anyio.sleep_forever()
                raise AssertionError
            case None:
                return httpx.Response(reply.status, content=reply.body, request=request)
            case _:
                assert_never(reply.error)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
        client = ChatOpenAI(
            model=model,
            max_retries=0,
            timeout=httpx.Timeout(120),
            api_key=SecretStr("transport-test-placeholder"),
            base_url="https://provider.invalid/v1",
            http_async_client=transport,
        )
        adapter = OpenAILLM(role, client)
        try:
            yield Harness(adapter, requests, client)
        finally:
            await adapter.aclose()
