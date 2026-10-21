"""Request-count regressions for the single retry owner and terminal failures."""

from typing import Self

import anyio
import pytest
from pydantic import BaseModel, ValidationInfo, model_validator

from agent.contracts import ContractModel, ContractViolation
from agent.essay_llm import ErrorKind, GenerationError, Output, Stage
from agent.fake_llm import FastLLM
from tests.llm_support import FactOutput, Reply, SuppliedFacts, completion, provider

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_invalid_json_and_timeout_share_budget() -> None:
    async with provider((completion("broken JSON"), Reply(error="timeout"))) as harness:
        with pytest.raises(GenerationError) as caught:
            _ = await harness.adapter.generate(
                "analyze_context", SuppliedFacts(facts=()), FactOutput
            )
    assert caught.value.kind == ErrorKind.TIMEOUT
    assert len(harness.requests) == 2
    assert len(caught.value.usage.attempts) == 2
    assert caught.value.usage.attempts[0].total_tokens == 18
    assert caught.value.usage.total_tokens is None


async def test_sdk_retries_disabled() -> None:
    async with provider((Reply(error="timeout"), Reply(error="timeout"))) as harness:
        assert harness.client.max_retries == 0
        with pytest.raises(GenerationError) as caught:
            _ = await harness.adapter.generate(
                "analyze_context", SuppliedFacts(facts=()), FactOutput
            )
    assert caught.value.kind == ErrorKind.TIMEOUT
    assert len(harness.requests) == 2


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_error_not_retried(status: int) -> None:
    async with provider((Reply('{"error":{"message":"private details"}}', status),)) as harness:
        with pytest.raises(GenerationError) as caught:
            _ = await harness.adapter.generate(
                "analyze_context", SuppliedFacts(facts=()), FactOutput
            )
    assert caught.value.kind == ErrorKind.AUTH
    assert len(harness.requests) == 1
    assert "private details" not in str(caught.value)


@pytest.mark.parametrize("status", [400, 404, 422])
async def test_bad_request_not_retried(status: int) -> None:
    async with provider((Reply('{"error":{"message":"bad schema"}}', status),)) as harness:
        with pytest.raises(GenerationError) as caught:
            _ = await harness.adapter.generate(
                "analyze_context", SuppliedFacts(facts=()), FactOutput
            )
    assert caught.value.kind == ErrorKind.REQUEST
    assert len(harness.requests) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_transient_status_retries_once(status: int) -> None:
    replies = (
        Reply('{"error":{"message":"transient"}}', status),
        completion('{"facts": [], "note": null}'),
    )
    async with provider(replies) as harness:
        result = await harness.adapter.generate(
            "analyze_context", SuppliedFacts(facts=()), FactOutput
        )
    assert len(harness.requests) == 2
    assert len(result.usage.attempts) == 2
    assert result.usage.attempts[1].total_tokens == 18


async def test_refusal_not_schema_retry() -> None:
    reply = completion('{"facts": [], "note": null}')
    refusal = Reply(reply.body.replace('"refusal": null', '"refusal": "cannot comply"'))
    async with provider((refusal,)) as harness:
        with pytest.raises(GenerationError) as caught:
            _ = await harness.adapter.generate(
                "analyze_context", SuppliedFacts(facts=()), FactOutput
            )
    assert caught.value.kind == ErrorKind.REFUSAL
    assert len(harness.requests) == 1
    assert caught.value.usage.total_tokens == 18


async def test_incomplete_output_is_not_success() -> None:
    async with provider((completion('{"facts": [', finish="length"),)) as harness:
        with pytest.raises(GenerationError) as caught:
            _ = await harness.adapter.generate(
                "analyze_context", SuppliedFacts(facts=()), FactOutput
            )
    assert caught.value.kind == ErrorKind.INCOMPLETE
    assert len(harness.requests) == 1
    assert caught.value.usage.total_tokens == 18


async def test_incomplete_response_uses_fallback_without_retry() -> None:
    failure_kind: ErrorKind | None = None
    fallback = FactOutput(facts=(), note="stage-owned fallback")
    async with provider((completion('{"facts": [', finish="length"),)) as harness:
        try:
            result = await harness.adapter.generate(
                "analyze_context",
                SuppliedFacts(facts=()),
                FactOutput,
            )
        except GenerationError as error:
            failure_kind = error.kind
            selected = fallback
        else:
            selected = result.output
    assert failure_kind == ErrorKind.INCOMPLETE
    assert selected == fallback
    assert len(harness.requests) == 1


async def test_cancelled_call_not_retried() -> None:
    async with provider((Reply(error="wait"),)) as harness:
        with anyio.move_on_after(0.1) as scope:
            _ = await harness.adapter.generate(
                "analyze_context", SuppliedFacts(facts=()), FactOutput
            )
        assert scope.cancel_called
    assert len(harness.requests) == 1


async def test_content_filter_not_retried() -> None:
    async with provider((completion("", finish="content_filter"),)) as harness:
        with pytest.raises(GenerationError) as caught:
            _ = await harness.adapter.generate(
                "analyze_context", SuppliedFacts(facts=()), FactOutput
            )
    assert caught.value.kind == ErrorKind.REFUSAL
    assert len(harness.requests) == 1


class _Context(BaseModel):
    payload: SuppliedFacts


class _Info(BaseModel):
    context: _Context | None


class ContextOutput(FactOutput):
    @model_validator(mode="after")
    def current_facts_only(self, info: ValidationInfo) -> Self:
        context = _Info.model_validate(info, from_attributes=True).context
        if context is not None:
            payload = context.payload
            if any(fact not in payload.facts for fact in self.facts):
                code = "unknown_fact"
                raise ContractViolation(code, "output used an absent fact")
        return self


async def test_reference_validation_shares_transport_budget() -> None:
    replies = (completion('{"facts": ["invented"], "note": null}'), Reply(error="timeout"))
    async with provider(replies) as harness:
        with pytest.raises(GenerationError) as caught:
            _ = await harness.adapter.generate(
                "analyze_context", SuppliedFacts(facts=()), ContextOutput
            )
    assert caught.value.kind == ErrorKind.TIMEOUT
    assert len(harness.requests) == 2
    assert caught.value.usage.attempts[0].total_tokens == 18


async def test_format_retry_succeeds_and_accounts_for_both_responses() -> None:
    replies = (completion('{"extra": true}'), completion('{"facts": [], "note": null}'))
    async with provider(replies) as harness:
        result = await harness.adapter.generate(
            "analyze_context", SuppliedFacts(facts=()), FactOutput
        )
    assert len(harness.requests) == 2
    assert result.usage.total_tokens == 36


async def test_connection_retries_once() -> None:
    replies = (Reply(error="connection"), completion('{"facts": [], "note": null}'))
    async with provider(replies) as harness:
        result = await harness.adapter.generate(
            "analyze_context", SuppliedFacts(facts=()), FactOutput
        )
    assert result.output.facts == ()
    assert len(harness.requests) == 2


async def test_cancellation_during_retry_delay_stops_second_request() -> None:
    async with provider((Reply(error="timeout"),)) as harness:
        with anyio.move_on_after(0.1) as scope:
            _ = await harness.adapter.generate(
                "analyze_context", SuppliedFacts(facts=()), FactOutput
            )
        assert scope.cancel_called
    assert len(harness.requests) == 1


async def test_fake_context_validation_uses_same_budget() -> None:
    factory = ConflictingFactory()
    with pytest.raises(GenerationError) as caught:
        _ = await FastLLM(factory).generate(
            "analyze_context", SuppliedFacts(facts=()), ContextOutput
        )
    assert caught.value.kind == ErrorKind.FORMAT
    assert factory.calls == 2
    assert len(caught.value.usage.attempts) == 2


class ConflictingFactory:
    """Count injected invalid outputs to expose fake retry behavior."""

    def __init__(self) -> None:
        self.calls: int = 0

    def __call__(
        self,
        stage: Stage,
        payload: ContractModel,
        output_model: type[Output],
    ) -> Output:
        self.calls += 1
        return output_model.model_validate({"facts": ["invented"], "note": None})
