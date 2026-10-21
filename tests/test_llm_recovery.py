import json

import anyio
import pytest
from typing_extensions import override

from agent.contracts import ContractModel, ContractViolation
from agent.essay_llm import ErrorKind, GenerationError, Output, Stage
from agent.fake_llm import FastLLM
from tests.llm_support import Reply, SuppliedFacts, completion, provider
from tests.test_retry import ContextOutput

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Recovery:
    def __init__(self) -> None:
        self.calls: int = 0
        self.saved: tuple[str, ...] = ()

    def __call__(self, parsed: ContractModel, payload: ContractModel) -> ContractModel:
        self.calls += 1
        output = ContextOutput.model_validate(parsed.model_dump())
        supplied = SuppliedFacts.model_validate(payload.model_dump())
        self.saved = tuple(dict.fromkeys((*self.saved, *output.facts)))
        return ContextOutput.model_validate(
            {"facts": tuple(fact for fact in self.saved if fact in supplied.facts), "note": None},
            context={"payload": supplied},
        )


def partial_reply(fact: str = "current") -> Reply:
    return completion(json.dumps({"facts": [fact, "invented"], "note": None}))


@pytest.mark.parametrize(
    ("second", "kind"),
    [
        (Reply(error="timeout"), ErrorKind.TIMEOUT),
        (completion("broken JSON"), ErrorKind.FORMAT),
        (completion("", finish="content_filter"), ErrorKind.REFUSAL),
    ],
)
async def test_partial_survives_later_failure(second: Reply, kind: ErrorKind) -> None:
    recover = Recovery()
    async with provider((partial_reply(), second)) as harness:
        with pytest.raises(GenerationError) as caught:
            _ = await harness.adapter.generate(
                "analyze_context",
                SuppliedFacts(facts=("current",)),
                ContextOutput,
                recover=recover,
            )
    assert caught.value.kind == kind
    assert caught.value.recovered == ContextOutput(facts=("current",), note=None)
    assert len(harness.requests) == 2
    assert len(caught.value.usage.attempts) == 2
    assert recover.calls == 1
    assert caught.value.recovered is not None
    assert "invented" not in caught.value.recovered.model_dump_json()


async def test_complete_success_wins() -> None:
    recover = Recovery()
    async with provider((partial_reply(), completion('{"facts": [], "note": "complete"}'))) as h:
        result = await h.adapter.generate(
            "analyze_context", SuppliedFacts(facts=("current",)), ContextOutput, recover=recover
        )
    assert result.output == ContextOutput(facts=(), note="complete")
    assert len(h.requests) == 2
    assert recover.calls == 1


async def test_latest_stage_merged_partial_is_retained() -> None:
    recover = Recovery()
    async with provider((partial_reply("first"), partial_reply("second"))) as h:
        with pytest.raises(GenerationError) as caught:
            _ = await h.adapter.generate(
                "analyze_context",
                SuppliedFacts(facts=("first", "second")),
                ContextOutput,
                recover=recover,
            )
    assert caught.value.recovered == ContextOutput(facts=("first", "second"), note=None)
    assert recover.calls == len(h.requests) == 2


@pytest.mark.parametrize(
    "first",
    [completion("broken"), completion('{"facts": ['), completion('{"facts": 3}')],
)
async def test_malformed_schema_has_no_recovery(first: Reply) -> None:
    recover = Recovery()
    async with provider((first, Reply(error="timeout"))) as h:
        with pytest.raises(GenerationError) as caught:
            _ = await h.adapter.generate(
                "analyze_context", SuppliedFacts(facts=()), ContextOutput, recover=recover
            )
    assert caught.value.recovered is None
    assert recover.calls == 0
    assert len(h.requests) == 2


@pytest.mark.parametrize("finish", ["length", "content_filter"])
async def test_terminal_first_response_never_recovers(finish: str) -> None:
    recover = Recovery()
    async with provider((completion('{"facts": ["invented"], "note": null}', finish=finish),)) as h:
        with pytest.raises(GenerationError) as caught:
            _ = await h.adapter.generate(
                "analyze_context", SuppliedFacts(facts=()), ContextOutput, recover=recover
            )
    assert caught.value.recovered is None
    assert recover.calls == 0
    assert len(h.requests) == 1


class RejectSecond(Recovery):
    @override
    def __call__(self, parsed: ContractModel, payload: ContractModel) -> ContractModel:
        if self.calls:
            code = "recovery_rejected"
            raise ContractViolation(code, "stage rejected partial")
        return super().__call__(parsed, payload)


class InvalidSecond(Recovery):
    @override
    def __call__(self, parsed: ContractModel, payload: ContractModel) -> ContractModel:
        if self.calls:
            return ContextOutput(facts=("invented",), note=None)
        return super().__call__(parsed, payload)


@pytest.mark.parametrize("recover", [RejectSecond(), InvalidSecond()])
async def test_rejected_callback_preserves_prior_partial(recover: Recovery) -> None:
    async with provider((partial_reply(), partial_reply())) as h:
        with pytest.raises(GenerationError) as caught:
            _ = await h.adapter.generate(
                "analyze_context", SuppliedFacts(facts=("current",)), ContextOutput, recover=recover
            )
    assert caught.value.recovered == ContextOutput(facts=("current",), note=None)
    assert len(h.requests) == 2


class PartialFactory:
    def __init__(self) -> None:
        self.calls: int = 0

    def __call__(self, stage: Stage, payload: ContractModel, output_model: type[Output]) -> Output:
        self.calls += 1
        supplied = SuppliedFacts.model_validate(payload.model_dump())
        return output_model.model_validate({"facts": (*supplied.facts, "invented"), "note": None})


async def test_fake_parity() -> None:
    factory = PartialFactory()
    recover = Recovery()
    with pytest.raises(GenerationError) as caught:
        _ = await FastLLM(factory).generate(
            "analyze_context", SuppliedFacts(facts=("current",)), ContextOutput, recover=recover
        )
    assert caught.value.recovered == ContextOutput(facts=("current",), note=None)
    assert factory.calls == recover.calls == 2


async def test_concurrent_payloads_are_isolated() -> None:
    results: dict[str, ContractModel | None] = {}

    async def generate(fact: str) -> None:
        async with provider((partial_reply(fact), Reply(error="timeout"))) as h:
            with pytest.raises(GenerationError) as caught:
                _ = await h.adapter.generate(
                    "analyze_context",
                    SuppliedFacts(facts=(fact,)),
                    ContextOutput,
                    recover=Recovery(),
                )
            results[fact] = caught.value.recovered
            assert len(h.requests) == 2

    async with anyio.create_task_group() as group:
        _ = group.start_soon(generate, "first")
        _ = group.start_soon(generate, "second")
    assert results == {
        "first": ContextOutput(facts=("first",), note=None),
        "second": ContextOutput(facts=("second",), note=None),
    }


def broken_recovery(parsed: ContractModel, payload: ContractModel) -> ContractModel:
    assert isinstance(parsed, ContextOutput)
    assert isinstance(payload, SuppliedFacts)
    message = "programming bug"
    raise RuntimeError(message)


async def test_programming_error_is_not_hidden() -> None:
    async with provider((partial_reply(),)) as h:
        with pytest.raises(RuntimeError, match="programming bug"):
            _ = await h.adapter.generate(
                "analyze_context",
                SuppliedFacts(facts=("current",)),
                ContextOutput,
                recover=broken_recovery,
            )
    assert len(h.requests) == 1


async def test_recovery_then_cancel_preserves_cancellation() -> None:
    recover = Recovery()
    async with provider((partial_reply(), Reply(error="wait"))) as h:
        with anyio.move_on_after(0.5) as scope:
            _ = await h.adapter.generate(
                "analyze_context",
                SuppliedFacts(facts=("current",)),
                ContextOutput,
                recover=recover,
            )
        assert scope.cancel_called
    assert recover.calls == 1
    assert len(h.requests) == 2


async def test_shared_fake_adapter_has_no_recovery_state() -> None:
    adapter = FastLLM(PartialFactory())
    results: dict[str, ContractModel | None] = {}

    async def generate(fact: str) -> None:
        with pytest.raises(GenerationError) as caught:
            _ = await adapter.generate(
                "analyze_context",
                SuppliedFacts(facts=(fact,)),
                ContextOutput,
                recover=Recovery(),
            )
        results[fact] = caught.value.recovered

    async with anyio.create_task_group() as group:
        _ = group.start_soon(generate, "first")
        _ = group.start_soon(generate, "second")
    assert results == {
        "first": ContextOutput(facts=("first",), note=None),
        "second": ContextOutput(facts=("second",), note=None),
    }
